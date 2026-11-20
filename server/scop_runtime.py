"""Run an offline PR-summary record audit against the existing SCOP validator."""

import argparse
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
from pathlib import Path
import runpy
import sys
from time import monotonic
from typing import BinaryIO

from .scop_core.core import discover, match


_ROOT = Path(__file__).resolve().parents[1]
_SKILL = "pr-source-summary"
_VALIDATOR = Path("tests") / _SKILL / "validate.py"
READ_RECORD = "local:read-summary-record"
MAX_RECORD_BYTES = 256_000
_MAX_TASK_CHARS = 4096
_LIMITATIONS = (
    "Checks one record's structure and reference format.",
    "Does not fetch GitHub evidence, verify claims or produce a new summary.",
)


class Status(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TaskRequest:
    task: str
    permissions: tuple[str, ...] = (READ_RECORD,)


@dataclass(frozen=True)
class ExecutionLog:
    status: Status
    elapsed_ms: float
    message: str


@dataclass(frozen=True)
class ExecutionError:
    code: str
    message: str


@dataclass(frozen=True)
class EvidenceReference:
    kind: str
    url: str
    locator: str


@dataclass(frozen=True)
class Audit:
    pr_url: str
    claims_checked: int
    references_checked: int


@dataclass
class TaskResult:
    status: Status = Status.QUEUED
    skill: str | None = None
    validator: str | None = None
    validation_mode: str | None = None
    duration_ms: float = 0.0
    logs: list[ExecutionLog] = field(default_factory=list)
    error: ExecutionError | None = None
    audit: Audit | None = None
    evidence_references: tuple[EvidenceReference, ...] = ()
    limitations: tuple[str, ...] = _LIMITATIONS


class _Blocked(ValueError):
    """The input is valid but the requested audit cannot proceed."""


class _InvalidInput(ValueError):
    """A safe input diagnostic that can be returned to callers."""


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidInput("JSON object keys must be unique")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise _InvalidInput("JSON does not allow NaN or Infinity literals")


def _audit_record(source: BinaryIO, result: TaskResult) -> tuple[Audit, tuple[EvidenceReference, ...]]:
    raw = source.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise _InvalidInput("summary record exceeds the input size limit")
    if not raw.strip():
        raise _InvalidInput("summary record is empty")
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object,
                            parse_constant=_reject_constant)
    except _InvalidInput:
        raise
    except (ValueError, RecursionError) as error:
        raise _InvalidInput("expected one UTF-8 JSON record") from error

    # This is an application-owned module at a fixed path. The request and
    # SKILL.md cannot supply code, module names, paths, or validator CLI flags.
    validate = runpy.run_path(str(_ROOT / _VALIDATOR))["validate"]
    result.validator = f"{_VALIDATOR.as_posix()}::validate"
    result.validation_mode = "offline_structure"
    try:
        _, sources = validate(record)
    except ValueError as error:
        # The validator sometimes includes an input locator in its error text.
        message = "summary record failed structural validation"
        if str(error).startswith("source URL does not match PR and locator: "):
            message = "source URL does not match PR and locator"
        raise _InvalidInput(message) from error
    if record["status"] == "blocked":
        raise _Blocked("the supplied summary record reports a blocked result")
    return (
        Audit(record["pr_url"], len(record["verified_facts"]), len(sources)),
        tuple(EvidenceReference(ref["kind"], ref["url"], ref["locator"]) for ref in sources),
    )


def run(request: TaskRequest, source: BinaryIO) -> TaskResult:
    """Synchronously run the supported adapter after checking permissions."""
    started = monotonic()
    result = TaskResult()

    def log(status: Status, message: str) -> None:
        result.status = status
        result.duration_ms = round((monotonic() - started) * 1000, 3)
        result.logs.append(ExecutionLog(status, result.duration_ms, message))

    def stop(status: Status, code: str, message: str) -> None:
        result.error = ExecutionError(code, message)
        log(status, message)

    log(Status.QUEUED, "Task received")
    try:
        if set(request.permissions) != {READ_RECORD}:
            stop(Status.BLOCKED, "permission_denied", "Only local summary record reads are allowed and required")
            return result
        if len(request.task) > _MAX_TASK_CHARS or not request.task.strip():
            raise _InvalidInput("task must contain 1 to 4096 characters and cannot be blank")
        ranked = match(request.task, discover(_ROOT / "skills"))
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            stop(Status.BLOCKED, "ambiguous_skill", "Multiple skills tied for the highest score")
            return result
        if ranked:
            result.skill = ranked[0][0].name
        if result.skill != _SKILL:
            stop(Status.BLOCKED, "no_adapter", "No supported skill matched the task")
            return result
        log(Status.RUNNING, "Validating the supplied PR-summary record")
        result.audit, result.evidence_references = _audit_record(source, result)
    except KeyboardInterrupt:
        stop(Status.CANCELLED, "interrupted", "Task interrupted")
    except _Blocked as error:
        stop(Status.BLOCKED, "record_blocked", str(error))
    except _InvalidInput as error:
        stop(Status.FAILED, "invalid_input", str(error))
    except OSError:
        stop(Status.FAILED, "read_failed", "Could not read a runtime dependency or the summary record")
    except Exception:
        stop(Status.FAILED, "execution_failed", "The audit could not finish")
    else:
        log(Status.COMPLETED, "Record structure and reference format passed")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit one local PR-summary JSON record supplied on stdin")
    parser.add_argument("task", help="Describe the PR-summary audit for Core skill matching")
    parser.add_argument("--permission", action="append", help=f"Replace the default grant ({READ_RECORD})")
    args = parser.parse_args()
    permissions = (READ_RECORD,) if args.permission is None else tuple(args.permission)
    result = run(TaskRequest(args.task, permissions), sys.stdin.buffer)
    print(json.dumps(asdict(result), indent=2))
    return {Status.COMPLETED: 0, Status.FAILED: 1, Status.BLOCKED: 2, Status.CANCELLED: 130}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
