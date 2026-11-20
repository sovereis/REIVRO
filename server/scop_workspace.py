"""Local JSON request/response boundary for the SCOP Workspace."""

import argparse
from dataclasses import asdict, dataclass
import json
import sys
from typing import BinaryIO

from .scop_github_evidence import GITHUB_READ
from .scop_runtime import ExecutionError, Status, _json_object, _reject_constant
from .scop_workflow import WorkflowRequest, WorkflowResult, run_workflow


MAX_REQUEST_BYTES = 32_768
_FIELDS = {"pr_url", "task", "permissions"}
_EXIT_CODES = {
    Status.COMPLETED: 0,
    Status.FAILED: 1,
    Status.BLOCKED: 2,
    Status.CANCELLED: 130,
}


@dataclass(frozen=True)
class WorkspaceResponse:
    execution: WorkflowResult | None = None
    request_error: ExecutionError | None = None
    contract_version: str = "0.6"


class _InvalidRequest(ValueError):
    """A safe request error for the caller."""


def _read_request(source: BinaryIO) -> WorkflowRequest:
    raw = source.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise _InvalidRequest("Request exceeds 32768 bytes")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object,
                             parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise _InvalidRequest("Expected one UTF-8 JSON request with unique object keys") from error
    if not isinstance(payload, dict) or payload.keys() - _FIELDS:
        raise _InvalidRequest("Expected a request object with only pr_url, permissions, and task fields")
    pr_url = payload.get("pr_url")
    if not isinstance(pr_url, str):
        raise _InvalidRequest("pr_url must be a string")
    permissions = payload.get("permissions", [])
    if not isinstance(permissions, list) or any(not isinstance(item, str) for item in permissions):
        raise _InvalidRequest("permissions must be an array of strings")
    if "task" in payload:
        if not isinstance(payload["task"], str):
            raise _InvalidRequest("task must be a string")
        return WorkflowRequest(pr_url, tuple(permissions), payload["task"])
    return WorkflowRequest(pr_url, tuple(permissions))


def handle_request(source: BinaryIO) -> tuple[int, WorkspaceResponse]:
    """Run one request with the workflow's server-side permission and URL checks."""
    try:
        request = _read_request(source)
    except KeyboardInterrupt:
        return 130, WorkspaceResponse(request_error=ExecutionError("interrupted", "Request interrupted"))
    except _InvalidRequest as error:
        return 1, WorkspaceResponse(request_error=ExecutionError("invalid_request", str(error)))
    except Exception:
        return 1, WorkspaceResponse(request_error=ExecutionError("read_failed", "Could not read the request"))

    try:
        execution = run_workflow(request)
    except KeyboardInterrupt:
        return 130, WorkspaceResponse(request_error=ExecutionError("interrupted", "Request interrupted"))
    except Exception:
        return 1, WorkspaceResponse(request_error=ExecutionError("execution_failed", "Workflow could not return a result"))
    return _EXIT_CODES[execution.status], WorkspaceResponse(execution=execution)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send one Workspace JSON request on stdin and receive one JSON response on stdout.",
        epilog=f"GitHub access requires explicit consent via permissions: [\"{GITHUB_READ}\"].",
    )
    parser.parse_args()
    exit_code, response = handle_request(sys.stdin.buffer)
    print(json.dumps(asdict(response), indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
