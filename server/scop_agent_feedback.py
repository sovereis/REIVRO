"""Private operator journal for agent feedback and correction authorization."""
from contextlib import contextmanager
import fcntl
import os
import stat

from .scop_firewall import Firewall
from .scop_firewall_memory import _private_directory, canonical

CORRECTION_LIMIT = 2
MAX_REPORT = 65536


@contextmanager
def review_lock(memory):
    """Serialize review attempts without holding SQLite's lock during VERIFY."""
    _private_directory(memory.directory)
    fd = os.open(memory.directory / "agent-review.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError("Untrusted review lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def recorded_report(memory, db, subject):
    for event in reversed(memory.history(db, subject)):
        if event["kind"] == "agent_result":
            return event["data"].get("report")
    return None


def record_report(memory, db, subject, result):
    report = {**result, "feedback": {"version": 1, "decision": "wait_for_operator"}}
    if len(canonical(report)) > MAX_REPORT // 2:
        raise ValueError("Feedback too large")
    memory.append(db, "agent_result", subject, {"status": result["status"], "report": report})
    return report


def checked_feedback(memory, report, event_id, *, authorize=False):
    subject = "agent-event-" + event_id
    with memory.transaction(write=authorize) as db:
        saved = recorded_report(memory, db, subject)
        if saved is None or ((authorize or report is not None) and canonical(saved) != canonical(report)):
            raise ValueError("Feedback does not match the operator journal")
        if not authorize:
            return saved
        if saved["status"] != "VIOLATION_DETECTED" or not saved["evidence"]:
            raise ValueError("Only an independently verified local violation is eligible")
        identifier = saved["protection"]["id"]
        if Firewall(memory)._active(db, identifier) is None:
            raise ValueError("Protection is no longer active")
        task_subject = "agent-task-" + saved["task_id"]
        history = memory.history(db, task_subject)
        grants = [entry["data"] for entry in history if entry["kind"] == "correction_authorized"]
        if len(grants) >= CORRECTION_LIMIT or any(grant["event_id"] == event_id for grant in grants):
            raise ValueError("Correction budget exhausted or already authorized")
        grant = {k: saved[k] for k in ("agent", "project", "task_id", "event_id", "pr", "requested_head_sha")}
        grant.update(protection_id=identifier, attempt=len(grants) + 1)
        memory.append(db, "correction_authorized", task_subject, grant)
        return {**saved, "feedback": {"version": 1, "decision": "correction_authorized",
                                      "attempt": grant["attempt"], "limit": CORRECTION_LIMIT}}


def link_correction(memory, db, item, parent_event, protection_id):
    subject = "agent-task-" + item["task_id"]
    history = memory.history(db, subject)
    grant = next((entry["data"] for entry in history if entry["kind"] == "correction_authorized"
                  and entry["data"]["event_id"] == parent_event), None)
    if (grant is None or any(grant[k] != item[k] for k in ("agent", "project", "task_id", "pr"))
            or grant["requested_head_sha"] == item["head_sha"] or item["event_id"] == parent_event
            or grant["protection_id"] != protection_id
            or Firewall(memory)._active(db, protection_id) is None
            or any(entry["data"]["parent_event"] == parent_event
                   for entry in history if entry["kind"] == "correction_submitted")):
        raise ValueError("Correction lacks a matching unused authorization")
    memory.append(db, "correction_submitted", subject,
                  {"parent_event": parent_event, "event_id": item["event_id"]})
