"""Run the read-only SCOP PR review workflow."""

import argparse
from dataclasses import asdict, dataclass, field
import json
import runpy
from time import monotonic
from typing import Callable, TypeVar
from uuid import uuid4

from .scop_core.core import discover, match
from .scop_github_evidence import GITHUB_READ, _Mismatch, _Unavailable, _VALIDATOR_PATH
from .scop_pr_summary import SummaryResult, _generate_draft, _parse_identity, _verify_draft
from .scop_runtime import Status, _MAX_TASK_CHARS, _ROOT


_DEFAULT_TASK = "summarize GitHub pull requests"
_SKILL = "pr-source-summary"
_T = TypeVar("_T")


@dataclass(frozen=True)
class WorkflowRequest:
    pr_url: str
    permissions: tuple[str, ...] = ()
    task: str = _DEFAULT_TASK


@dataclass
class StepResult:
    name: str
    requires: tuple[str, ...] = ()
    status: Status = Status.QUEUED
    duration_ms: float | None = None
    error_code: str | None = None


@dataclass
class WorkflowResult(SummaryResult):
    execution_id: str = field(default_factory=lambda: str(uuid4()))
    skill: str | None = None
    steps: dict[str, StepResult] = field(default_factory=lambda: {
        "validate_request": StepResult("validate_request"),
        "select_skill": StepResult("select_skill", ("validate_request",)),
        "generate_summary": StepResult("generate_summary", ("select_skill",)),
        "verify_evidence": StepResult("verify_evidence", ("generate_summary",)),
    })


class _Stop(Exception):
    def __init__(self, status: Status, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _check_request(request: WorkflowRequest):
    if request.permissions != (GITHUB_READ,):
        raise _Stop(Status.BLOCKED, "permission_denied", "Explicit github:read-pr-evidence permission is required")
    if not isinstance(request.task, str) or len(request.task) > _MAX_TASK_CHARS or not request.task.strip():
        raise _Stop(Status.FAILED, "invalid_task", "Expected a nonblank task of at most 4096 characters")
    schema = runpy.run_path(str(_VALIDATOR_PATH))
    identity = _parse_identity(request.pr_url, schema)
    if identity is None:
        raise _Stop(Status.FAILED, "invalid_pr_url", "Expected a canonical public GitHub PR URL")
    return identity, schema


def _select_skill(task: str) -> str:
    ranked = match(task, discover(_ROOT / "skills"))
    if not ranked or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        raise _Stop(Status.BLOCKED, "no_unique_skill", "No unique skill matched the task")
    return ranked[0][0].name


def run_workflow(request: WorkflowRequest) -> WorkflowResult:
    started = monotonic()
    result = WorkflowResult()

    def event(status: Status, message: str) -> None:
        result.status = status
        result.duration_ms = round((monotonic() - started) * 1000, 3)
        result.events.append({"status": status, "elapsed_ms": result.duration_ms, "message": message})

    def execute(name: str, action: Callable[[], _T]) -> _T:
        step = result.steps[name]
        step_started = monotonic()
        step.status = Status.RUNNING
        try:
            try:
                if any(result.steps[dependency].status != Status.COMPLETED for dependency in step.requires):
                    raise _Stop(Status.BLOCKED, "dependency_incomplete", "A required step has not completed")
                value = action()
            except KeyboardInterrupt as error:
                raise _Stop(Status.CANCELLED, "interrupted", "Workflow interrupted") from error
            except _Unavailable as error:
                raise _Stop(Status.BLOCKED, "github_unavailable", str(error)) from error
            except _Mismatch as error:
                raise _Stop(Status.FAILED, "evidence_mismatch", "A generated excerpt did not match GitHub evidence") from error
            except _Stop:
                raise
            except Exception as error:
                raise _Stop(Status.FAILED, "step_failed", "Workflow step could not complete") from error
        except _Stop as error:
            step.status, step.error_code = error.status, error.code
            raise
        else:
            step.status = Status.COMPLETED
            return value
        finally:
            step.duration_ms = round((monotonic() - step_started) * 1000, 3)

    def select_adapter() -> None:
        result.skill = _select_skill(request.task)
        if result.skill != _SKILL:
            raise _Stop(Status.BLOCKED, "unsupported_skill", "The selected skill has no workflow adapter")

    event(Status.QUEUED, "PR workflow requested")
    event(Status.RUNNING, "Starting sequential checks")
    try:
        identity, schema = execute("validate_request", lambda: _check_request(request))
        result.pr_url = request.pr_url
        execute("select_skill", select_adapter)
        draft = execute("generate_summary", lambda: _generate_draft(request.pr_url, identity))
        execute("verify_evidence", lambda: _verify_draft(draft, schema, result))
    except _Stop as error:
        result.error_code, result.error_message = error.code, str(error)
        event(error.status, str(error))
    else:
        event(Status.COMPLETED, "All required steps completed")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr_url", help="Canonical public GitHub pull request URL")
    parser.add_argument("--task", default=_DEFAULT_TASK, help="Task description for skill selection")
    parser.add_argument("--permission", action="append", default=[], help=f"Required opt-in: {GITHUB_READ}")
    args = parser.parse_args()
    result = run_workflow(WorkflowRequest(args.pr_url, tuple(args.permission), args.task))
    print(json.dumps(asdict(result), indent=2))
    return {Status.COMPLETED: 0, Status.FAILED: 1, Status.BLOCKED: 2, Status.CANCELLED: 130}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
