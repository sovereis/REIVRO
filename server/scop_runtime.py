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
_VALIDATOR = _ROOT / "tests" / _SKILL / "validate.py"
READ_RECORD = "local:read-summary-record"
MAX_RECORD_BYTES = 256_000
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
    duration_ms: float = 0.0
    logs: list[ExecutionLog] = field(default_factory=list)
    error: ExecutionError | None = None
    audit: Audit | None = None
    evidence_references: tuple[EvidenceReference, ...] = ()
    limitations: tuple[str, ...] = _LIMITATIONS


class _Blocked(ValueError):
    """The input is valid but the requested audit cannot proceed."""


def _audit_record(source: BinaryIO) -> tuple[Audit, tuple[EvidenceReference, ...]]:
    raw = source.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("summary record exceeds the input size limit")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as error:
        raise ValueError("expected one UTF-8 JSON record") from error

    # This is an application-owned module at a fixed path. The request and
    # SKILL.md cannot supply code, module names, paths, or validator CLI flags.
    validate = runpy.run_path(str(_VALIDATOR))["validate"]
    _, sources = validate(record)
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
        ranked = match(request.task, discover(_ROOT / "skills"))
        if ranked:
            result.skill = ranked[0][0].name
        tied = len(ranked) > 1 and ranked[0][1] == ranked[1][1]
        if result.skill != _SKILL or tied:
            stop(Status.BLOCKED, "no_adapter", "No unambiguous match for the configured PR-summary audit")
            return result
        log(Status.RUNNING, "Validating the supplied PR-summary record")
        result.audit, result.evidence_references = _audit_record(source)
    except KeyboardInterrupt:
        stop(Status.CANCELLED, "interrupted", "Task interrupted")
    except _Blocked as error:
        stop(Status.BLOCKED, "record_blocked", str(error))
    except ValueError as error:
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
