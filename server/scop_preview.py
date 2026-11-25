"""REIVRO Developer Preview V0.1. Local static verification for operators."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess

from . import scop_task_verification as task
from .scop_agent_feedback import checked_feedback
from .scop_agent_integration import read_json, uuid_text
from .scop_firewall import Firewall
from .scop_firewall_memory import FirewallError, Memory

REVIEW_ACTIONS = {
    "none": "No operator action is required.",
    "review_task_evidence": "Review task evidence and any unresolved policies.",
    "review_policy_violation": "Review the policy violation before authorizing a correction.",
}


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--project", default=os.environ.get("REIVRO_PROJECT"), help="Trusted owner/repository")
    cli.add_argument("--store", default=os.environ.get("REIVRO_STORE"), help="Private operator directory")
    cli.add_argument("--checkout", default=".", help="Trusted Git checkout (default: current directory)")
    cli.add_argument("--json", action="store_true", help="Emit structured JSON")
    commands = cli.add_subparsers(dest="command", required=True)
    for command in ("init", "doctor", "status", "demo"):
        commands.add_parser(command)
    history = commands.add_parser("history", help="Show a recorded verification by event ID")
    history.add_argument("event")
    contract = commands.add_parser("task", help="Approve the task contract supplied on standard input")
    contract.add_argument("decision", choices=["approve"])
    verify = commands.add_parser("verify", help="Verify the agent submission supplied on standard input")
    verify.add_argument("digest")
    verify.add_argument("--after-correction", metavar="EVENT")
    review = commands.add_parser("review", help="Capture evidence or explicitly decide a finding")
    actions = review.add_subparsers(dest="action", required=True)
    capture = actions.add_parser("capture")
    capture.add_argument("event")
    choice = capture.add_mutually_exclusive_group(required=True)
    choice.add_argument("--criterion", type=int)
    choice.add_argument("--violation", type=int)
    for name in ("confirm", "reject"):
        decision = actions.add_parser(name)
        decision.add_argument("finding")
        decision.add_argument("--reason", required=True)
    protect = commands.add_parser("protect")
    actions = protect.add_subparsers(dest="action", required=True)
    actions.add_parser("propose").add_argument("finding")
    export = actions.add_parser("export")
    export.add_argument("protection")
    export.add_argument("--private", action="store_true", help="Restore the private runtime artifact")
    approval = actions.add_parser("approve")
    approval.add_argument("protection")
    approval.add_argument("--reason", required=True)
    revoke = commands.add_parser("revoke")
    revoke.add_argument("protection")
    revoke.add_argument("--reason", required=True)
    commands.add_parser("authorize-correction").add_argument("event")
    return cli


def execute(args, payload=None):
    if args.command == "demo":
        from .scop_preview_demo import demo
        return demo()
    if not args.project or not args.store:
        return {"status": "ERROR", "reason": "Set REIVRO_PROJECT and REIVRO_STORE or pass --project and --store."}
    memory = Memory(args.store, args.project)
    firewall = Firewall(memory)
    git = task.GitObjects(args.checkout)
    artifacts = memory.directory
    match args.command:
        case "init":
            head = git.head()
            try:
                memory.initialize()
            except FileExistsError:
                with memory.transaction():
                    pass
            return {"status": "READY", "project": memory.repository, "head": head}
        case "doctor":
            try:
                head = git.head()
            except (OSError, task.GitUnavailable):
                return {"status": "ERROR", "reason": "Use an operator-controlled Git checkout with a committed HEAD and /usr/bin/git."}
            try:
                with memory.transaction():
                    pass
            except FileNotFoundError:
                return {"status": "ERROR", "reason": "Initialize the project with reivro init."}
            except (FirewallError, OSError, sqlite3.Error):
                return {"status": "ERROR", "reason": "Check the project match, journal integrity, and owner-only permissions."}
            return {"status": "READY", "project": memory.repository, "head": head, "mode": "local_static"}
        case "status":
            return {"status": "READY", "project": memory.repository, "activity": firewall.metrics()}
        case "task":
            return task.approve(memory, payload, git)
        case "verify":
            return task.verify(memory, payload, args.digest, git, {}, artifact_checkout=artifacts,
                               project_policies=True, after_correction=args.after_correction)
        case "history":
            return checked_feedback(memory, None, uuid_text(args.event))
        case "authorize-correction":
            event = uuid_text(args.event)
            saved = checked_feedback(memory, None, event)
            return checked_feedback(memory, saved, event, authorize=True)
        case "review":
            if args.action == "capture":
                return task.capture_finding(memory, args.event, criterion_index=args.criterion,
                                            violation_index=args.violation)
            decision = firewall.decide_finding(args.finding, args.action, args.reason)
            return {"status": decision["kind"].upper(), "finding_id": args.finding}
        case "protect":
            if args.action == "propose":
                proposal = firewall.propose(args.finding)
                return {"status": "PROPOSED", "protection_id": proposal["protection_id"],
                        "state": proposal["state"], "policy": proposal["artifact"].get("policy")}
            if args.action == "approve":
                firewall.decide_protection(args.protection, "approve", args.reason)
            target = artifacts if args.action == "approve" or args.private else Path(args.checkout)
            exported = firewall.export(args.protection, target)
            return {"status": "EXPORTED", **exported}
        case "revoke":
            firewall.decide_protection(args.protection, "revoke", args.reason)
            return {"status": "REVOKED", "protection_id": args.protection}
    raise ValueError("Unknown command")


def human(report):
    lines = [f"Result: {report['status'].replace('_', ' ')}"]
    if "agent_declaration" in report:
        lines.append(f"Agent declaration: {report['agent_declaration']['agent']} reported completion.")
        lines.append(f"Independent task result: {report['task_status'].replace('_', ' ')}")
        for criterion in report.get("criteria", []):
            lines.append(f"Criterion {criterion['index']} ({criterion['kind']}): {criterion['outcome']}")
        for violation in report.get("violations", []):
            lines.append(f"Task scope violation: {violation['reason']} ({violation['path_sha256']})")
        for policy in report.get("policies", []):
            lines.append(f"Policy {policy['id']}: {policy['state']}")
            if policy["recurrence"]:
                lines.append(f"Confirmed recurrence. Original evidence: {policy['source_evidence_id']}")
        if report.get("evidence"):
            evidence = report["evidence"]
            lines.append(f"Evidence: {report['evidence_id']}")
            lines.append(f"Verified BASE: {evidence['base_sha']}")
            lines.append(f"Verified HEAD: {evidence['head_sha']}")
        else:
            lines.append("Git evidence is unavailable.")
        lines.append(f"Next action: {REVIEW_ACTIONS[report['operator_action']]}")
    for key in ("reason", "project", "head", "task_id", "event_id", "digest", "finding_id",
                "protection_id", "artifact_sha256", "path"):
        if key in report:
            lines.append(f"{key.replace('_', ' ').capitalize()}: {report[key]}")
    if report.get("feedback", {}).get("decision") == "correction_authorized":
        lines.append("Correction authorized by the operator.")
    for step in report.get("steps", []):
        lines.append(f"{step['name']}: {step['status']}")
    if report.get("synthetic"):
        lines.append("Synthetic tasks and agent labels. Local Git and real REIVRO verification.")
    if "activity" in report:
        lines.extend(f"{key.replace('_', ' ').capitalize()}: {value}" for key, value in report["activity"].items()
                     if value is not None)
    return "\n".join(lines)


def main():
    args = parser().parse_args()
    try:
        size = {"task": 32768, "verify": 4096}.get(args.command)
        report = execute(args, read_json(size) if size else None)
    except (FirewallError, ValueError, TypeError, OSError, sqlite3.Error, subprocess.SubprocessError,
            task.GitUnavailable):
        report = {"status": "ERROR",
                  "reason": "Operation rejected. Check the private journal, trusted checkout, IDs, and input schema."}
    print(json.dumps(report, ensure_ascii=True) if args.json else human(report))
    if report.get("feedback", {}).get("decision") == "correction_authorized":
        return 0
    return {"ERROR": 1, "INCONCLUSIVE": 1, "INCOMPLETE": 2, "POLICY_VIOLATION": 2}.get(report["status"], 0)
