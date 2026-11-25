"""Local VERIFY → CONFIRM → LEARN → PREVENT alpha for public GitHub PRs."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import re
import sqlite3
from time import monotonic
from uuid import uuid4

from .scop_firewall_memory import FirewallError, Memory, artifact, canonical, identifier, project_key
from .scop_github_evidence import GITHUB_READ
from .scop_task_policy import CATEGORY as TASK_POLICY, VERSION as TASK_POLICY_VERSION
from .scop_verify_syntax import RULE, verify_syntax

VERIFIER_VERSION = "verify-v2"
PROTECTION_VERSION = 1
_PROTECTION_TRANSITIONS = {
    "protection": {"protection_approved", "protection_rejected"},
    "protection_approved": {"protection_revoked"},
}
_PR = re.compile(r"https://github\.com/([^/]+/[^/]+)/pull/([1-9][0-9]{0,9})")
_SHA = re.compile(r"[0-9a-f]{40}")


class Firewall:
    def __init__(self, memory):
        self.memory = memory

    def _check_pr(self, url, permission):
        if not permission:
            raise FirewallError("Explicit --github-read is required")
        match = _PR.fullmatch(url) if len(url) <= 250 else None
        if not match or project_key(match[1]) != self.memory.repository:
            raise FirewallError("Expected a public GitHub PR URL for this project")
        return int(match[2])

    def _verify(self, url, pr):
        started = monotonic()
        report = verify_syntax(url, (GITHUB_READ,))
        status = report.get("status")
        if status not in {"REGRESSION_DETECTED", "PASS", "INCONCLUSIVE", "ERROR"}:
            report = {"status": "ERROR", "reason": "Unknown verifier result"}
        if status in {"REGRESSION_DETECTED", "PASS"}:
            files = report.get("files")
            if (report.get("rule") != RULE or report.get("pr_url") != url or report.get("pr") != pr
                    or not isinstance(files, list) or not files
                    or any(not isinstance(item, dict) or "status" not in item for item in files)
                    or not isinstance(report.get("repository"), str)
                    or report["repository"].lower() != self.memory.repository
                    or not all(isinstance(report.get(key), str) and _SHA.fullmatch(report[key])
                               for key in ("base_sha", "head_sha"))):
                report = {"status": "ERROR", "reason": "Verifier returned inconsistent PR identity or evidence"}
            elif status == "PASS" and any(item["status"] != "PASS" for item in files):
                report = {"status": "ERROR", "reason": "Verifier returned an inconsistent PASS"}
            elif status == "REGRESSION_DETECTED" and (
                not any(item["status"] == status for item in files)
                or any(item["status"] == status and item.get("rule") != RULE for item in files)
            ):
                report = {"status": "ERROR", "reason": "Verifier returned no matching regression evidence"}
        return {"report": report, "pr_url": url, "verifier_version": VERIFIER_VERSION,
                "duration_ms": round((monotonic() - started) * 1000, 3), "cost": None}

    @staticmethod
    def _pin(analysis, expected_head):
        if expected_head is not None:
            report = analysis["report"]
            actual = report.get("head_sha")
            if actual != expected_head and (actual is not None or report["status"] != "ERROR"):
                return {**analysis, "report": {"status": "INCONCLUSIVE",
                        "reason": "Verified HEAD differs from requested revision"}}
        return analysis

    def analyze(self, url, permission, *, expected_head=None, on_record=None):
        pr = self._check_pr(url, permission)
        with self.memory.transaction():
            pass
        analysis = self._pin(self._verify(url, pr), expected_head)
        with self.memory.transaction(write=True) as db:
            result = self._record_analysis(db, analysis)
            if on_record is not None:
                on_record(db, result)
            return result

    def _record_analysis(self, db, analysis):
        report = analysis["report"]
        analysis_id = "a-" + uuid4().hex
        findings = []
        if report["status"] == "REGRESSION_DETECTED":
            for item in report["files"]:
                if item["status"] != "REGRESSION_DETECTED":
                    continue
                evidence = {key: report[key] for key in
                            ("repository", "pr_url", "pr", "base_sha", "head_sha", "compiler")}
                evidence.update(verifier_version=VERIFIER_VERSION, result=report["status"], finding=item)
                finding_id = identifier("f", evidence)
                if not self.memory.history(db, finding_id):
                    self.memory.append(db, "finding", finding_id, {**evidence, "first_analysis_id": analysis_id})
                findings.append(finding_id)
        result = {"analysis_id": analysis_id, "finding_ids": findings, **analysis}
        self.memory.append(db, "analysis", analysis_id, result)
        return result

    def _events(self, db, subject, expected):
        prefix = {"finding": "f", "protection": "p"}[expected]
        if not re.fullmatch(prefix + r"-[0-9a-f]{64}", subject):
            raise FirewallError(f"Invalid {expected} ID")
        events = self.memory.history(db, subject)
        if not events or events[0]["kind"] != expected:
            raise FirewallError(f"Unknown {expected} for this project")
        original = events[0]["data"]
        evidence = {key: value for key, value in original.items() if key != "first_analysis_id"} if (
            expected == "finding"
        ) else original
        if identifier(prefix, evidence) != subject:
            raise FirewallError(f"Stored {expected} does not match its ID")
        if expected == "finding":
            decisions = events[1:]
            if len(decisions) > 1 or any(
                event["kind"] not in {"finding_confirmed", "finding_rejected"}
                or event["actor"] != self.memory.actor
                or event["data"].get("evidence_digest") != subject[2:]
                or event["data"].get("verifier_version") != original["verifier_version"]
                for event in decisions
            ):
                raise FirewallError("Invalid finding decision history")
        return events

    def decide_finding(self, finding_id, decision, reason):
        decision = {"confirm": "finding_confirmed", "reject": "finding_rejected"}.get(decision)
        reason = self._reason(reason)
        with self.memory.transaction(write=True) as db:
            events = self._events(db, finding_id, "finding")
            if decision is None or len(events) != 1:
                raise FirewallError("Finding requires a valid first decision")
            return self.memory.append(db, decision, finding_id, {
                "reason": reason,
                "evidence_digest": finding_id.removeprefix("f-"),
                "verifier_version": events[0]["data"]["verifier_version"],
            })

    def propose(self, finding_id):
        with self.memory.transaction(write=True) as db:
            finding, *history = self._events(db, finding_id, "finding")
            if not history or history[-1]["kind"] != "finding_confirmed":
                raise FirewallError("Explicitly confirm the finding before proposing a protection")
            data = {
                "category": RULE, "rule_version": VERIFIER_VERSION, "version": PROTECTION_VERSION,
                "source_finding_id": finding_id, "source_head_sha": finding["data"]["head_sha"],
                "scope": {"repository": self.memory.repository, "pull_requests": "public",
                          "files": "existing Python files eligible under VERIFY v2"},
                "trigger": "REGRESSION_DETECTED",
            }
            limitations = "Syntax only. Requires comparable BASE/HEAD evidence and the VERIFY compiler sandbox."
            if finding["data"]["verifier_version"] == TASK_POLICY_VERSION:
                data.update(category=TASK_POLICY, rule_version=TASK_POLICY_VERSION,
                            scope={"repository": self.memory.repository},
                            trigger="POLICY_VIOLATION", policy=finding["data"]["policy"])
                limitations = "Static task policy. Requires an operator-selected contract and trusted Git objects."
            protection_id = identifier("p", data)
            if not self.memory.history(db, protection_id):
                self.memory.append(db, "protection", protection_id, data)
            return {"protection_id": protection_id, "artifact": data,
                    "state": self._protection_state(self._events(db, protection_id, "protection"))["kind"],
                    "original_finding": finding["data"],
                    "limitations": limitations}

    def decide_protection(self, protection_id, decision, reason):
        reason = self._reason(reason)
        transitions = {
            ("protection", "approve"): "protection_approved",
            ("protection", "reject"): "protection_rejected",
            ("protection_approved", "revoke"): "protection_revoked",
        }
        with self.memory.transaction(write=True) as db:
            events = self._events(db, protection_id, "protection")
            next_state = transitions.get((self._protection_state(events)["kind"], decision))
            if next_state is None:
                raise FirewallError("Invalid protection transition")
            return self.memory.append(db, next_state, protection_id, {
                "reason": reason, "artifact_digest": protection_id.removeprefix("p-"),
            })

    @staticmethod
    def _reason(reason):
        if not 0 < len(reason.strip()) <= 1000:
            raise FirewallError("A justification of 1–1000 characters is required")
        return reason.strip()

    def _protection_state(self, events):
        state = events[0]
        for event in events[1:]:
            if event["kind"] == "protection_exported" and state["kind"] == "protection_approved":
                continue
            if (event["kind"] not in _PROTECTION_TRANSITIONS.get(state["kind"], ())
                    or event["actor"] != self.memory.actor
                    or event["data"].get("artifact_digest") != state["subject"][2:]):
                raise FirewallError("Invalid protection decision history")
            state = event
        return state

    def _active(self, db, protection_id):
        events = self._events(db, protection_id, "protection")
        approval = self._protection_state(events)
        if approval["kind"] != "protection_approved":
            return None
        data = events[0]["data"]
        finding = self._events(db, data["source_finding_id"], "finding")
        if (finding[-1]["kind"] != "finding_confirmed"
                or finding[0]["data"]["head_sha"] != data["source_head_sha"]
                or data["scope"]["repository"] != self.memory.repository):
            raise FirewallError("Protection has no matching confirmed finding for this project")
        if (data["category"], data["rule_version"], data["version"]) not in {
            (RULE, VERIFIER_VERSION, PROTECTION_VERSION),
            (TASK_POLICY, TASK_POLICY_VERSION, PROTECTION_VERSION),
        }:
            return None
        if data["category"] == TASK_POLICY and (
            finding[0]["data"]["verifier_version"] != TASK_POLICY_VERSION
            or finding[0]["data"].get("policy") != data.get("policy")
        ):
            raise FirewallError("Task policy does not match the confirmed finding")
        return {"protection_id": protection_id, **data, "approval": {
            "actor": approval["actor"], "time": approval["time"],
        }}

    def export(self, protection_id, checkout):
        with self.memory.transaction(write=True) as db:
            manifest = self._active(db, protection_id)
            if manifest is None:
                raise FirewallError("Only an approved, active protection can be exported")
            path = artifact(checkout, protection_id, manifest)
            self.memory.append(db, "protection_exported", protection_id, {"version": manifest["version"]})
            result = {"path": path, "protection_id": protection_id}
            if manifest["category"] == TASK_POLICY:
                result["artifact_sha256"] = sha256(canonical(manifest) + b"\n").hexdigest()
            return result

    def run(self, protection_id, checkout, url, permission, *, expected_head=None, on_record=None):
        pr = self._check_pr(url, permission)
        run_id = "r-" + uuid4().hex
        with self.memory.transaction(write=True) as db:
            manifest = self._active(db, protection_id)
            if manifest is None or manifest["category"] != RULE:
                result = {"status": "INAPPLICABLE", "reason": "Protection is inactive or unsupported"}
                return self._record_run(db, run_id, protection_id, url, result, on_record)
            try:
                exported = artifact(checkout, protection_id)
            except (OSError, FirewallError):
                result = {"status": "ERROR", "reason": "Cannot read the protection artifact safely"}
                return self._record_run(db, run_id, protection_id, url, result, on_record)
            if exported != canonical(manifest) + b"\n":
                result = {"status": "ERROR", "reason": "Artifact does not match the approved protection version"}
                return self._record_run(db, run_id, protection_id, url, result, on_record)
            self.memory.append(db, "protection_run_started", run_id, {
                "protection_id": protection_id, "pr_url": url, "version": PROTECTION_VERSION,
            })

        try:
            analysis = self._pin(self._verify(url, pr), expected_head)
        except KeyboardInterrupt:
            with self.memory.transaction(write=True) as db:
                return self._record_run(db, run_id, protection_id, url, {
                    "status": "ERROR", "reason": "Protection run interrupted",
                    "version": PROTECTION_VERSION,
                }, on_record)
        report = analysis["report"]
        head = report.get("head_sha")
        with self.memory.transaction(write=True) as db:
            recorded = self._record_analysis(db, analysis)
            result = {"analysis_id": recorded["analysis_id"], "head_sha": head,
                      "version": PROTECTION_VERSION, "duration_ms": analysis["duration_ms"],
                      "cost": analysis["cost"]}
            if self._active(db, protection_id) != manifest:
                result.update(status="INAPPLICABLE", reason="Protection was revoked during execution")
            elif not self._artifact_matches(checkout, protection_id, manifest):
                result.update(status="ERROR", reason="Protection artifact changed during execution")
            elif head == manifest["source_head_sha"]:
                result.update(status="INAPPLICABLE", reason="HEAD matches original failure")
            else:
                result["status"] = {
                    "REGRESSION_DETECTED": "VIOLATION_DETECTED", "PASS": "NO_VIOLATION",
                    "INCONCLUSIVE": "INCONCLUSIVE", "ERROR": "ERROR",
                }[report["status"]]
            return self._record_run(db, run_id, protection_id, url, result, on_record)

    @staticmethod
    def _artifact_matches(checkout, protection_id, manifest):
        try:
            return artifact(checkout, protection_id) == canonical(manifest) + b"\n"
        except (OSError, FirewallError):
            return False

    def _record_run(self, db, run_id, protection_id, url, result, on_record=None):
        entry = {"run_id": run_id, "protection_id": protection_id, "pr_url": url, **result}
        self.memory.append(db, "protection_run_finished", run_id, entry)
        if on_record is not None:
            on_record(db, entry)
        return entry

    def history(self, subject=None):
        with self.memory.transaction() as db:
            return self.memory.history(db, subject)

    def metrics(self):
        events = self.history()
        counts = Counter(event["kind"] for event in events)
        executions = [event["data"] for event in events if event["kind"] == "protection_run_finished"]
        analyses = [event["data"] for event in events if event["kind"] == "analysis"]
        return {
            "analyses": counts["analysis"], "findings_confirmed": counts["finding_confirmed"],
            "findings_rejected": counts["finding_rejected"], "protections_proposed": counts["protection"],
            "protections_approved": counts["protection_approved"],
            "protections_executed": sum("analysis_id" in run for run in executions),
            "recurrences_detected": sum(run["status"] == "VIOLATION_DETECTED" for run in executions),
            "inconclusive_analyses": sum(item["report"]["status"] == "INCONCLUSIVE" for item in analyses),
            "inconclusive_runs": sum(run["status"] == "INCONCLUSIVE" for run in executions),
            "analysis_duration_ms": round(sum(item["duration_ms"] for item in analyses), 3),
            "cost": None,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, help="Private directory outside the Git checkout")
    parser.add_argument("--repository", required=True, help="GitHub owner/repository")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("metrics")
    commands.add_parser("show").add_argument("id", nargs="?")
    commands.add_parser("propose").add_argument("id")
    for name, choices in (("review", ("confirm", "reject")), ("decide", ("approve", "reject", "revoke"))):
        action = commands.add_parser(name)
        action.add_argument("id")
        action.add_argument("decision", choices=choices)
        action.add_argument("--reason", required=True)
    for name in ("analyze", "run"):
        action = commands.add_parser(name)
        if name == "run":
            action.add_argument("id")
            action.add_argument("--checkout", required=True)
        action.add_argument("url")
        action.add_argument("--github-read", action="store_true")
    export = commands.add_parser("export")
    export.add_argument("id")
    export.add_argument("--checkout", required=True)
    args = parser.parse_args()
    try:
        memory = Memory(args.store, args.repository)
        firewall = Firewall(memory)
        match args.command:
            case "init":
                memory.initialize()
                result = {"repository": memory.repository, "actor": memory.actor}
            case "analyze":
                result = firewall.analyze(args.url, args.github_read)
            case "review":
                result = firewall.decide_finding(args.id, args.decision, args.reason)
            case "propose":
                result = firewall.propose(args.id)
            case "decide":
                result = firewall.decide_protection(args.id, args.decision, args.reason)
            case "export":
                result = firewall.export(args.id, args.checkout)
            case "run":
                result = firewall.run(args.id, args.checkout, args.url, args.github_read)
            case "show":
                result = firewall.history(args.id)
            case "metrics":
                result = firewall.metrics()
    except FirewallError as exc:
        result = {"status": "ERROR", "reason": str(exc)}
    except (OSError, sqlite3.Error):
        result = {"status": "ERROR", "reason": "Local memory or artifact operation failed"}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    status = result.get("status", result.get("report", {}).get("status")) if isinstance(result, dict) else None
    return {"ERROR": 1, "INCONCLUSIVE": 2, "INAPPLICABLE": 2, "REGRESSION_DETECTED": 3,
            "VIOLATION_DETECTED": 3}.get(status, 0)


if __name__ == "__main__":
    raise SystemExit(main())
