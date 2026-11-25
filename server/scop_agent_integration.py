"""Versioned, operator-run verification for agent-submitted PR references."""
import argparse
from hashlib import sha256
import json
import os
import re
import sys
from uuid import UUID

from .scop_agent_feedback import (MAX_REPORT, checked_feedback, link_correction,
                                  record_report, recorded_report, review_lock)
from .scop_firewall import Firewall
from .scop_firewall_checks import StagingMemory
from .scop_firewall_memory import Memory, identifier, project_key
from .scop_firewall_pilot import STAGING

AGENTS = ("codex", "claude-code", "cursor", "independent")
FIELDS = {"version", "agent", "project", "task_id", "event_id", "pr", "head_sha"}
MAX_REQUEST = 4096
SHA = re.compile(r"[0-9a-f]{40}")
FINDING = re.compile(r"f-[0-9a-f]{64}")
STATUS = {"ERROR", "INCONCLUSIVE", "PASS", "REGRESSION_DETECTED", "INAPPLICABLE",
          "VIOLATION_DETECTED", "NO_VIOLATION", "OBSERVED", "VIOLATION", "INACTIVE"}


def uuid_text(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid UUID")
    return value


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate fields")
    return result


def validate(item):
    if (not isinstance(item, dict) or set(item) != FIELDS or type(item["version"]) is not int
            or item["version"] != 1 or item["agent"] not in AGENTS):
        raise ValueError("Invalid contract")
    if type(item["pr"]) is not int or not 0 < item["pr"] < 2**31:
        raise ValueError("Invalid PR")
    if not isinstance(item["head_sha"], str) or not SHA.fullmatch(item["head_sha"]):
        raise ValueError("Invalid Git revision")
    uuid_text(item["task_id"])
    uuid_text(item["event_id"])
    return {**item, "project": project_key(item["project"])}


def public_result(item, status, *, report=None, finding_ids=(), protection=None, evidence_kind=None):
    if status not in STATUS:
        raise ValueError("Unexpected verification state")
    report = report or {}
    files = []
    for file in report.get("files", ()):
        path = file.get("file")
        if isinstance(path, str) and file.get("status") in STATUS:
            entry = {"path_sha256": sha256(path.encode()).hexdigest(), "status": file["status"]}
            if type(file.get("line")) is int and file["line"] > 0:
                entry["line"] = file["line"]
            files.append(entry)
    verifier_status = report.get("status")
    if verifier_status not in {"REGRESSION_DETECTED", "PASS", "INCONCLUSIVE", "ERROR"}:
        verifier_status = None
    evidence = None
    if evidence_kind and report.get("head_sha") == item["head_sha"]:
        base = report.get("base_sha")
        if isinstance(base, str) and SHA.fullmatch(base):
            evidence = {"source": evidence_kind, "base_sha": base, "head_sha": item["head_sha"],
                        "pr": f"https://github.com/{item['project']}/pull/{item['pr']}"}
    return {"version": 1, "agent": item["agent"], "project": item["project"],
            "task_id": item["task_id"], "event_id": item["event_id"], "pr": item["pr"],
            "requested_head_sha": item["head_sha"], "status": status,
            "verifier_status": verifier_status, "evidence": evidence,
            "modified_files": files, "findings": list(finding_ids), "protection": protection}


def local_result(firewall, item, *, protection, checkout, commit):
    url = f"https://github.com/{item['project']}/pull/{item['pr']}"

    def record(db, outcome):
        if protection is None:
            analysis = outcome
            result = analysis["report"]["status"]
            applied = None
        else:
            result = outcome["status"]
            applied = {"id": protection, "application": {
                "VIOLATION_DETECTED": "violation", "NO_VIOLATION": "checked",
                "INAPPLICABLE": "inactive",
            }.get(result, "unconfirmed")}
            analysis = (firewall.memory.history(db, outcome["analysis_id"])[0]["data"]
                        if "analysis_id" in outcome else {})
        ids = [value for value in analysis.get("finding_ids", ()) if FINDING.fullmatch(value)]
        commit(db, public_result(item, result, report=analysis.get("report"), finding_ids=ids,
                                 protection=applied, evidence_kind="verified_public_pr"))

    if protection is None:
        firewall.analyze(url, True, expected_head=item["head_sha"], on_record=record)
    else:
        firewall.run(protection, checkout, url, True, expected_head=item["head_sha"], on_record=record)


def cloud_result(item, ref, repository_id, run_id, env):
    if ref != STAGING:
        raise ValueError("Expected authorized staging")
    memory = StagingMemory(ref, env["REIVRO_PUBLISHABLE_KEY"], env["REIVRO_AGENT_READER_JWT"])
    record = memory.read_run(repository_id, uuid_text(run_id))
    if record is None:
        return public_result(item, "INCONCLUSIVE")
    run = record["run"]
    if (run.get("id") != run_id or run.get("pr") != item["pr"]
            or run.get("head_sha") != item["head_sha"]):
        return public_result(item, "INCONCLUSIVE")
    outcome = run.get("outcome")
    report = run.get("report")
    if not isinstance(report, dict) or outcome not in STATUS:
        return public_result(item, "INCONCLUSIVE")
    if (report.get("repository", "").lower() != item["project"] or
            report.get("head_sha") != item["head_sha"] or report.get("base_sha") != run.get("base_sha")):
        return public_result(item, "INCONCLUSIVE")
    protection = run.get("protection_id")
    # This is historical evidence. It does not assert that the protection is still active.
    protection = {"id": uuid_text(protection), "application": "historical"} if protection else None
    findings = [uuid_text(f["id"]) for f in record["findings"]]
    return public_result(item, outcome, report=report, evidence_kind="staging_run",
                         protection=protection, finding_ids=findings)


def review(item, args, env):
    item = validate(item)
    if item["project"] != project_key(args.repository):
        raise ValueError("Unexpected project")
    memory = Memory(args.store, args.repository)
    subject = "agent-event-" + item["event_id"]
    parent = getattr(args, "after_correction", None)
    identity = [item, args.cloud_run, args.repository_id, args.protection]
    if parent is not None:
        identity.append(uuid_text(parent))
    fingerprint = identifier("submission", identity)
    with review_lock(memory):
        with memory.transaction(write=True) as db:
            prior = memory.history(db, subject)
            if prior:
                if prior[0]["data"]["fingerprint"] != fingerprint:
                    raise ValueError("Conflicting event")
                if any(event["kind"] == "agent_result" for event in prior):
                    return public_result(item, "INCONCLUSIVE") | {"reason": "duplicate_event"}
                if prior[0]["data"].get("journal") != 2:
                    return public_result(item, "INCONCLUSIVE") | {"reason": "legacy_reservation"}
            else:
                if parent is not None:
                    link_correction(memory, db, item, parent, args.protection)
                memory.append(db, "agent_submission", subject, {"fingerprint": fingerprint, "journal": 2})

        def commit(db, result):
            record_report(memory, db, subject, result)

        try:
            if args.cloud_run:
                result = cloud_result(item, env["REIVRO_STAGING_REF"], args.repository_id,
                                      args.cloud_run, env)
                with memory.transaction(write=True) as db:
                    commit(db, result)
            else:
                local_result(Firewall(memory), item, protection=args.protection,
                             checkout=args.checkout, commit=commit)
        except Exception:
            with memory.transaction(write=True) as db:
                if recorded_report(memory, db, subject) is None:
                    commit(db, public_result(item, "ERROR") | {"reason": "integration_failed"})
        with memory.transaction() as db:
            return recorded_report(memory, db, subject)


def read_json(limit):
    raw = sys.stdin.buffer.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Oversized input")
    return json.loads(raw, object_pairs_hook=unique_object)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    submit = commands.add_parser("submit")
    submit.add_argument("--agent", choices=AGENTS, default="independent")
    submit.add_argument("--project", required=True)
    submit.add_argument("--task-id", required=True)
    submit.add_argument("--event-id", required=True)
    submit.add_argument("--pr", required=True, type=int)
    submit.add_argument("--head-sha", required=True)
    action = commands.add_parser("review")
    action.add_argument("--repository", required=True)
    action.add_argument("--store", required=True)
    action.add_argument("--github-read", action="store_true")
    action.add_argument("--protection")
    action.add_argument("--checkout")
    action.add_argument("--cloud-run")
    action.add_argument("--repository-id", type=int)
    action.add_argument("--after-correction")
    for name in ("feedback", "authorize-correction"):
        decision = commands.add_parser(name)
        decision.add_argument("--repository", required=True)
        decision.add_argument("--store", required=True)
        decision.add_argument("--event-id", required=True)
        if name == "feedback":
            decision.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "submit":
            result = validate({k: getattr(args, k) for k in FIELDS - {"version"}} | {"version": 1})
        elif args.command in {"feedback", "authorize-correction"}:
            recover = getattr(args, "recover", False)
            report = None if recover else read_json(MAX_REPORT)
            if not recover and not isinstance(report, dict):
                raise ValueError("Expected a feedback report")
            result = checked_feedback(Memory(args.store, args.repository), report,
                                      uuid_text(args.event_id), authorize=args.command == "authorize-correction")
        else:
            if args.after_correction and (args.cloud_run or not args.protection):
                raise ValueError("A correction requires a local protection")
            if args.cloud_run:
                if not args.repository_id or args.protection or args.checkout or args.github_read:
                    raise ValueError("Expected trusted repository ID and cloud run")
            elif not args.github_read or bool(args.protection) != bool(args.checkout) or args.repository_id:
                raise ValueError("Expected explicit read authorization and paired protection/checkout")
            if args.protection and not re.fullmatch(r"p-[0-9a-f]{64}", args.protection):
                raise ValueError("Invalid protection ID")
            result = review(read_json(MAX_REQUEST), args, os.environ)
    except Exception:
        result = {"version": 1, "status": "ERROR", "reason": "request_or_integration_failed"}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    status = result.get("status")
    if status == "OBSERVED" and result.get("verifier_status") == "REGRESSION_DETECTED":
        return 2
    if status in {"ERROR", "INCONCLUSIVE", "INACTIVE", "INAPPLICABLE", "OBSERVED"}:
        return 1
    return 2 if status in {"VIOLATION", "VIOLATION_DETECTED", "REGRESSION_DETECTED"} else 0


if __name__ == "__main__":
    sys.exit(main())
