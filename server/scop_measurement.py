"""Local SCOP experiment records and explicit human feedback."""

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
import fcntl
import io
import json
from math import isfinite
import os
from pathlib import Path
import stat
import sys
from uuid import UUID, uuid4

from .scop_runtime import _json_object, _reject_constant
from .scop_workspace import handle_request


LOCAL_WRITE = "local:write-measurements"
MAX_REQUEST_BYTES = 65_536
MAX_RECORD_BYTES = 8192
MAX_RESPONSE_BYTES = 2_000_000
MAX_EXECUTIONS = 1000
_MAX_DURATION_MS = 7 * 24 * 60 * 60 * 1000
_DECISIONS = {"accepted", "needs_rework"}


class MeasurementError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _require(condition, message):
    if not condition:
        raise MeasurementError("invalid_request", message)


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object,
                          parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise MeasurementError("invalid_request", "Expected one strict UTF-8 JSON object") from error


def _fields(value, required, optional=()):
    _require(isinstance(value, dict) and set(required) <= value.keys() <= set(required) | set(optional),
             "Unexpected or missing object fields")


def _execution_id(value):
    _require(isinstance(value, str) and len(value) == 36, "Expected a canonical execution UUID")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise MeasurementError("invalid_request", "Expected a canonical execution UUID") from error
    _require(parsed.version == 4 and str(parsed) == value, "Expected a canonical execution UUID")
    return value


def _integer(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def _duration(value):
    if value is None:
        return None
    _fields(value, {"milliseconds", "provenance"})
    _require(_integer(value["milliseconds"], _MAX_DURATION_MS), "Invalid human duration in milliseconds")
    _require(value["provenance"] in ("human_measured", "human_reported"), "Invalid human duration provenance")
    return value


def _feedback(value):
    _fields(value, {"decision"}, {"notes", "review", "rework", "correction_cycles"})
    _require(value["decision"] in ("accepted", "needs_rework"), "Expected accepted or needs_rework")
    notes = value.get("notes")
    _require(notes is None or (isinstance(notes, str) and len(notes) <= 1000
                               and not any(0xD800 <= ord(char) <= 0xDFFF for char in notes)),
             "Notes must be valid text of at most 1000 characters")
    cycles = value.get("correction_cycles")
    _require(cycles is None or _integer(cycles, 10_000), "Invalid correction cycle count")
    return {"decision": value["decision"], "notes": notes, "review": _duration(value.get("review")),
            "rework": _duration(value.get("rework")), "correction_cycles": cycles}


def _utc_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        _require(parsed.tzinfo == UTC and parsed.isoformat() == value, "Invalid UTC timestamp")
    except (TypeError, ValueError) as error:
        raise MeasurementError("invalid_request", "Invalid UTC timestamp") from error


def _execution_record(value):
    _fields(value, {"execution_id", "status", "duration_ms", "references_checked", "references_verified"})
    _execution_id(value["execution_id"])
    status, duration = value["status"], value["duration_ms"]
    checked, verified = value["references_checked"], value["references_verified"]
    _require(status in ("completed", "failed", "blocked", "cancelled"), "Invalid execution status")
    _require(type(duration) in (int, float) and 0 <= duration <= _MAX_DURATION_MS and isfinite(duration),
             "Invalid execution duration")
    _require(_integer(checked, 10_000) and _integer(verified, checked), "Inconsistent citation counts")
    _require(status != "completed" or checked == verified > 0, "Completed execution lacks verified evidence")
    return value


def _privacy(info, mode):
    return info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == mode


@contextmanager
def _open_store(directory):
    """Walk the configured absolute path without following symlinks."""
    path = Path(directory).absolute()
    _require(path != Path("/") and ".." not in path.parts, "Expected a dedicated private store directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            try:
                marker = os.stat(".git", dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(marker.st_mode):
                    os.stat(".git/HEAD", dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise MeasurementError("unsafe_store", "Store must be outside Git worktrees")
        if not _privacy(os.fstat(fd), 0o700):
            raise MeasurementError("unsafe_store", "Store must be owner-only with mode 0700")
        yield fd
    finally:
        os.close(fd)


def _read(fd, name):
    try:
        data_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None
    with os.fdopen(data_fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or not _privacy(info, 0o600):
            raise MeasurementError("storage_failed", "Unsafe local record")
        raw = source.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise MeasurementError("storage_failed", "Oversized local record")
    try:
        return _json(raw)
    except MeasurementError as error:
        raise MeasurementError("storage_failed", "Unreadable local record") from error


def _index(fd):
    runs, feedback = set(), set()
    with os.scandir(fd) as entries:
        for count, entry in enumerate(entries, 1):
            if count > 2 * MAX_EXECUTIONS:
                raise MeasurementError("storage_failed", "Local experiment exceeds the record limit")
            identity, _, kind = entry.name.partition(".")
            if kind not in {"run", "feedback"}:
                raise MeasurementError("storage_failed", "Unexpected entry in the dedicated store")
            (runs if kind == "run" else feedback).add(_execution_id(identity))
    if len(runs) > MAX_EXECUTIONS or feedback - runs:
        raise MeasurementError("storage_failed", "Inconsistent local experiment index")
    return runs


def _write(fd, name, record):
    raw = json.dumps(record, allow_nan=False).encode()
    if len(raw) > MAX_RECORD_BYTES:
        raise MeasurementError("storage_failed", "Local record exceeds the size limit")
    temp = f".pending-{uuid4()}"
    data_fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(data_fd, "wb") as sink:
            os.fchmod(sink.fileno(), 0o600)
            sink.write(raw)
            sink.flush()
            os.fsync(sink.fileno())
        try:
            os.link(temp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        except FileExistsError as error:
            raise MeasurementError("duplicate_record", "A record already exists for this execution") from error
    finally:
        os.unlink(temp, dir_fd=fd)
    os.fsync(fd)


def _get(fd, identity):
    record = _read(fd, f"{identity}.run")
    if record is None:
        raise MeasurementError("unknown_execution", "No recorded execution has that ID")
    try:
        _execution_record(record)
        _require(record["execution_id"] == identity, "Execution identity does not match")
        feedback = _read(fd, f"{identity}.feedback")
        if feedback is not None:
            _fields(feedback, {"execution_id", "timestamp_utc", "evaluation"})
            _require(feedback["execution_id"] == identity and record["status"] == "completed",
                     "Feedback does not match an eligible execution")
            _utc_timestamp(feedback["timestamp_utc"])
            _require(_feedback(feedback["evaluation"]) == feedback["evaluation"],
                     "Invalid stored evaluation")
    except MeasurementError as error:
        raise MeasurementError("storage_failed", "Inconsistent local measurement record") from error
    return record, feedback


def _quantity(milliseconds, provenance):
    return {"milliseconds": milliseconds, "provenance": provenance}


def _measurement(record, feedback):
    evaluation = feedback["evaluation"] if feedback else {}
    execution = _quantity(record["duration_ms"], "system_observed")
    review, rework = evaluation.get("review"), evaluation.get("rework")
    values = [metric["milliseconds"] for metric in (execution, review, rework) if metric is not None]
    return {
        "execution_duration": execution, "human_review_duration": review, "human_rework_duration": rework,
        "total_observed_task_time": {**_quantity(round(sum(values), 3), "derived"),
                                     "complete": review is not None and rework is not None},
        "citation_verification_coverage": _ratio(record["references_verified"], record["references_checked"]),
    }


def _ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None, "unit": "fraction", "provenance": "derived"}


def _aggregate(rows, complete):
    decisions = [feedback["evaluation"]["decision"] for _, feedback in rows if feedback is not None]
    return {
        "recorded_attempts": len(rows),
        "eligible_evaluations": len(decisions),
        "acceptance_rate": _ratio(decisions.count("accepted"), len(decisions)),
        "rework_rate": _ratio(decisions.count("needs_rework"), len(decisions)),
        "citation_verification_coverage": _ratio(
            sum(run["references_verified"] for run, _ in rows), sum(run["references_checked"] for run, _ in rows)
        ),
        "workflow_completion_rate": _ratio(
            sum(run["status"] == "completed" for run, _ in rows) if complete else None,
            len(rows) if complete else None,
        ),
        "complete_observation_set_attested": complete,
    }


def _operation(fd, request):
    operation = request["operation"]
    if operation == "run":
        code, response = handle_request(io.BytesIO(json.dumps(request["request"]).encode()))
        execution = response.execution
        if execution is None:
            return code, {"workspace_error": asdict(response.request_error) if response.request_error else None}
        record = _execution_record({key: getattr(execution, key) for key in
            ("execution_id", "status", "duration_ms", "references_checked", "references_verified")})
        workspace = asdict(response)
        if len(json.dumps(workspace, allow_nan=False).encode()) > MAX_RESPONSE_BYTES // 2:
            raise MeasurementError("response_too_large", "Workflow response exceeds the measurement limit")
        # Only this path can create an execution record. Input never supplies it.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if len(_index(fd)) >= MAX_EXECUTIONS:
            raise MeasurementError("storage_failed", "Local experiment is full")
        if record["status"] == "completed" and execution.summary is None:
            raise MeasurementError("storage_failed", "Completed execution lacks a verified summary")
        _write(fd, f'{record["execution_id"]}.run', record)
        return code, {"workspace": workspace, "measurement": _measurement(record, None)}

    if operation in ("get", "feedback"):
        identity = _execution_id(request["execution_id"])
        if operation == "feedback":
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record, feedback = _get(fd, identity)
        if operation == "feedback":
            if record["status"] != "completed":
                raise MeasurementError("ineligible_execution", "Only completed executions can receive feedback")
            if feedback is not None:
                raise MeasurementError("duplicate_feedback", "Feedback already exists and cannot be changed")
            feedback = {"execution_id": identity, "timestamp_utc": datetime.now(UTC).isoformat(),
                        "evaluation": _feedback(request["evaluation"])}
            _write(fd, f"{identity}.feedback", feedback)
        return 0, {"execution": record, "feedback": feedback, "measurement": _measurement(record, feedback)}

    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    rows = [_get(fd, identity) for identity in _index(fd)]
    aggregate = _aggregate(rows, request.get("complete_observation_set", False))
    if operation == "aggregate":
        return 0, aggregate
    # No identifiers, URLs, free text, or timestamps leave via export.
    dataset = [{
        "technical_status": record["status"],
        "decision": feedback["evaluation"]["decision"] if feedback else None,
        "correction_cycles": feedback["evaluation"]["correction_cycles"] if feedback else None,
        "measurement": _measurement(record, feedback),
    } for record, feedback in rows]
    dataset.sort(key=lambda row: json.dumps(row, sort_keys=True))
    return 0, {"aggregate": aggregate, "observations": dataset}


_OPERATIONS = {
    "run": ({"request"}, {"permissions"}),
    "feedback": ({"execution_id", "evaluation"}, {"permissions"}),
    "get": ({"execution_id"}, set()),
    "aggregate": (set(), {"complete_observation_set"}),
    "export": (set(), {"complete_observation_set"}),
}


def handle_request_bytes(raw: bytes, directory) -> tuple[int, dict]:
    result = {"contract_version": "0.7", "result": None, "error": None}
    try:
        _require(len(raw) <= MAX_REQUEST_BYTES, "Measurement request exceeds the size limit")
        request = _json(raw)
        operation = request.get("operation") if isinstance(request, dict) else None
        _require(isinstance(operation, str) and operation in _OPERATIONS, "Unknown measurement operation")
        required, optional = _OPERATIONS[operation]
        _fields(request, {"operation"} | required, optional)
        _require(type(request.get("complete_observation_set", False)) is bool,
                 "complete_observation_set must be boolean")
        if operation in ("run", "feedback") and request.get("permissions") != [LOCAL_WRITE]:
            raise MeasurementError("permission_denied", "Explicit local:write-measurements permission is required")
        with _open_store(directory) as fd:
            code, result["result"] = _operation(fd, request)
        return code, result
    except MeasurementError as error:
        result["error"] = {"code": error.code, "message": str(error)}
        return (2 if error.code == "permission_denied" else 1), result
    except RecursionError:
        result["error"] = {"code": "invalid_request", "message": "Request nesting exceeds the supported limit"}
        return 1, result
    except OSError:
        result["error"] = {"code": "storage_failed", "message": "Could not access the private measurement store"}
        return 1, result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-dir", required=True, help="Dedicated owner-only directory outside Git worktrees")
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        code, result = handle_request_bytes(raw, args.store_dir)
    except (OSError, KeyboardInterrupt) as error:
        interrupted = isinstance(error, KeyboardInterrupt)
        code = 130 if interrupted else 1
        result = {"contract_version": "0.7", "result": None, "error": {
            "code": "interrupted" if interrupted else "read_failed",
            "message": "Measurement was interrupted" if interrupted else "Could not read the measurement request",
        }}

    output = json.dumps(result, allow_nan=False)
    if len(output.encode()) > MAX_RESPONSE_BYTES:
        output = json.dumps({"contract_version": "0.7", "result": None, "error": {
            "code": "response_too_large", "message": "Measurement response exceeds the size limit",
        }})
        code = 1
    print(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
