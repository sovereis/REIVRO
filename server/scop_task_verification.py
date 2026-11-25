"""Operator-approved static task verification against immutable Git objects."""
import argparse
from hashlib import sha256
import json
import os
import re
from selectors import DefaultSelector, EVENT_READ
import subprocess
import sys
from time import monotonic

from .scop_agent_feedback import link_correction, recorded_report, record_report
from .scop_agent_integration import SHA, read_json, validate, uuid_text
from .scop_firewall import Firewall
from . import scop_task_policy as policy_rules
from .scop_firewall_checks import StagingMemory
from .scop_firewall_memory import FirewallError, Memory, identifier, project_key
from .scop_firewall_pilot import STAGING

RULE = "task-completion-v1"
DIGEST = re.compile(r"[0-9a-f]{64}")
PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
LIMIT = 256 * 1024


def valid_path(value):
    return (isinstance(value, str) and len(value) <= 240 and PATH.fullmatch(value)
            and not {".", "..", ".git"}.intersection(part.lower() for part in value.split("/")))


def task_contract(item):
    fields = {"version", "task_id", "project", "base_sha", "objective", "allowed_paths",
              "protected_paths", "criteria"}
    if (not isinstance(item, dict) or set(item) != fields or type(item["version"]) is not int
            or item["version"] != 1):
        raise ValueError("Invalid task contract")
    uuid_text(item["task_id"])
    if (not isinstance(item["base_sha"], str) or not SHA.fullmatch(item["base_sha"])
            or not isinstance(item["objective"], str) or not item["objective"].strip()
            or len(item["objective"]) > 2048):
        raise ValueError("Invalid task objective or BASE")
    for name in ("allowed_paths", "protected_paths"):
        paths = item[name]
        if (not isinstance(paths, list) or len(paths) > 128 or not all(map(valid_path, paths))
                or len(set(paths)) != len(paths)):
            raise ValueError("Invalid path scope")
    criteria = item["criteria"]
    if not isinstance(criteria, list) or not 0 < len(criteria) <= 32:
        raise ValueError("Expected bounded acceptance criteria")
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise ValueError("Invalid criterion")
        kind = criterion.get("kind")
        if kind in ("exists", "changed") and set(criterion) == {"kind", "path"}:
            if valid_path(criterion["path"]):
                continue
        if kind == "blob_sha256" and set(criterion) == {"kind", "path", "digest"}:
            if valid_path(criterion["path"]) and isinstance(criterion["digest"], str) and DIGEST.fullmatch(criterion["digest"]):
                continue
        if kind == "manual" and set(criterion) == {"kind"}:
            continue
        if kind == "cloud_run" and set(criterion) == {"kind", "repository_id", "run_id", "outcome"}:
            uuid_text(criterion["run_id"])
            if (type(criterion["repository_id"]) is int and 0 < criterion["repository_id"] < 2**63
                    and criterion["outcome"] in ("PASS", "OBSERVED")):
                continue
        raise ValueError("Unsupported or malformed criterion")
    return {**item, "project": project_key(item["project"])}


class GitUnavailable(Exception):
    pass


class GitObjects:
    """Read a trusted operator checkout with a fixed binary and no shell."""

    def __init__(self, checkout):
        self.checkout = checkout

    def read(self, *args, limit=LIMIT):
        deadline = monotonic() + 5
        with subprocess.Popen(
            ["/usr/bin/git", "--no-replace-objects", "-C", self.checkout, *args],
            env={"PATH": os.defpath, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_LITERAL_PATHSPECS": "1",
                 "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "",
                 "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ) as proc, DefaultSelector() as selector:
            selector.register(proc.stdout, EVENT_READ)
            data = bytearray()
            try:
                while selector.select(max(0, deadline - monotonic())):
                    if monotonic() >= deadline:
                        raise GitUnavailable
                    chunk = os.read(proc.stdout.fileno(), min(65536, limit + 1 - len(data)))
                    if not chunk:
                        if proc.wait(timeout=max(0, deadline - monotonic())) != 0:
                            raise GitUnavailable
                        return bytes(data)
                    data.extend(chunk)
                    if len(data) > limit:
                        raise GitUnavailable
                raise GitUnavailable
            except subprocess.TimeoutExpired:
                raise GitUnavailable from None
            finally:
                if proc.poll() is None:
                    proc.kill()

    def head(self):
        return self.read("rev-parse", "--verify", "HEAD^{commit}", limit=64).decode("ascii").strip()

    def blob(self, head, path, *, digest=False):
        entry = self.read("ls-tree", "-z", head, "--", path, limit=512)
        if not entry:
            return False
        metadata, name = entry.rstrip(b"\0").split(b"\t", 1)
        mode, kind, oid = metadata.split()
        if kind != b"blob" or mode not in {b"100644", b"100755"} or name != path.encode():
            return False
        if not digest:
            return True
        return sha256(self.read("cat-file", "blob", oid.decode("ascii"))).hexdigest()


def subject(task_id):
    return "task-contract-" + task_id


def approve(memory, contract, git):
    contract = task_contract(contract)
    if memory.repository != contract["project"] or git.head() != contract["base_sha"]:
        raise ValueError("Expected trusted project at the approved BASE")
    digest = identifier("task", contract)
    with memory.transaction(write=True) as db:
        if memory.history(db, subject(contract["task_id"])):
            raise ValueError("Task contract already has a decision")
        memory.append(db, "task_approved", subject(contract["task_id"]),
                      {"digest": digest, "contract": contract})
    return {"status": "APPROVED", "task_id": contract["task_id"], "digest": digest}


def active_contract(memory, db, task_id, digest):
    events = memory.history(db, subject(task_id))
    if not events or events[-1]["kind"] != "task_approved":
        raise ValueError("Task has no active operator approval")
    stored = events[0]["data"]
    contract = task_contract(stored["contract"])
    if digest != stored["digest"] or digest != identifier("task", contract):
        raise ValueError("Approved contract digest mismatch")
    return contract


def revoke(memory, task_id, digest):
    with memory.transaction(write=True) as db:
        active_contract(memory, db, task_id, digest)
        memory.append(db, "task_revoked", subject(task_id), {"digest": digest})
    return {"status": "REVOKED", "task_id": task_id, "digest": digest}


def cloud_evidence(criterion, contract, head, env):
    if env.get("REIVRO_STAGING_REF") != STAGING:
        return None
    try:
        memory = StagingMemory(STAGING, env["REIVRO_PUBLISHABLE_KEY"], env["REIVRO_AGENT_READER_JWT"])
        record = memory.read_run(criterion["repository_id"], criterion["run_id"])
        if record is None:
            return None
        run = record["run"]
        report = run.get("report") or {}
        return (run.get("id") == criterion["run_id"] and run.get("head_sha") == head
                and run.get("base_sha") == contract["base_sha"] and run.get("outcome") == criterion["outcome"]
                and str(report.get("repository", "")).lower() == contract["project"]
                and report.get("head_sha") == head and report.get("base_sha") == contract["base_sha"]
                and report.get("verification_status", report.get("status")) == "PASS")
    except Exception:
        return None


def inspect(contract, git, head, env, *, policy=None, policies=None):
    if git.head() != head:
        return {"status": "INCONCLUSIVE", "reason": "head_mismatch"}
    base = contract["base_sha"]
    try:
        git.read("merge-base", "--is-ancestor", base, head, limit=0)
    except GitUnavailable:
        return {"status": "INCONCLUSIVE", "reason": "base_ancestry_unconfirmed"}
    paths = set(git.read("diff-tree", "--no-commit-id", "--name-only", "--no-renames",
                         "--no-ext-diff", "--no-textconv", "-r", "-z", base, head).split(b"\0")) - {b""}
    allowed = {path.encode() for path in contract["allowed_paths"]}
    protected = {path.encode() for path in contract["protected_paths"]}
    violations = [{"path_sha256": sha256(path).hexdigest(),
                   "reason": "protected_path" if path in protected else "out_of_scope"}
                  for path in sorted((paths - allowed) | (paths & protected))]
    criteria = []
    for index, criterion in enumerate(contract["criteria"]):
        kind = criterion["kind"]
        if kind == "manual":
            observed = None
        elif kind == "cloud_run":
            observed = cloud_evidence(criterion, contract, head, env)
        else:
            path = criterion["path"]
            if kind == "changed":
                observed = False
                if path.encode() in paths:
                    current = git.blob(head, path, digest=True)
                    observed = bool(current) and current != git.blob(base, path, digest=True)
            elif kind == "exists":
                observed = git.blob(head, path) is True
            else:
                observed = git.blob(head, path, digest=True) == criterion["digest"]
        criteria.append({"index": index, "kind": kind,
                         "outcome": {True: "met", False: "unmet", None: "unverified"}[observed]})
    policy_paths = policy_rules.evaluate(policy, git, head, paths) if policy else []
    policy_set_paths = {key: policy_rules.evaluate(rule, git, head, paths)
                        for key, rule in (policies or {}).items()}
    if git.head() != head:
        return {"status": "INCONCLUSIVE", "reason": "head_moved"}
    outcomes = {criterion["outcome"] for criterion in criteria}
    status = ("POLICY_VIOLATION" if violations else "INCOMPLETE" if "unmet" in outcomes else
              "INCONCLUSIVE" if "unverified" in outcomes else "VERIFIED")
    return {"status": status, "base_sha": base, "observed_head_sha": head,
            "criteria": criteria, "violations": violations, "policy_paths": policy_paths, "policy_set_paths": policy_set_paths}


def capture_finding(memory, event_id, *, criterion_index=None, violation_index=None):
    """Operator-only selection of one eligible observation from the private journal."""
    with memory.transaction(write=True) as db:
        entries = memory.history(db, "task-event-" + uuid_text(event_id))
        if len(entries) != 1 or entries[0]["kind"] != "task_verified":
            raise ValueError("No verified task event")
        report = entries[0]["data"]["report"]
        evidence_id = report["evidence_id"]
        if (report.get("project") != memory.repository or
                evidence_id != identifier("task-evidence", {k: v for k, v in report.items() if k != "evidence_id"})):
            raise ValueError("Task evidence digest mismatch")
        contract = active_contract(memory, db, report["task_id"], report["contract_digest"])
        policy, paths = policy_rules.from_failure(contract, report, criterion_index, violation_index)
        evidence = {"repository": memory.repository, "head_sha": report["observed_head_sha"],
                    "verifier_version": policy_rules.VERSION, "task_id": report["task_id"],
                    "event_id": event_id, "evidence_id": evidence_id, "policy": policy,
                    "failure_keys": [policy_rules.failure_key(memory.repository, policy, path) for path in paths],
                    "criterion_index": criterion_index, "violation_index": violation_index}
        finding_id = identifier("f", evidence)
        if not memory.history(db, finding_id):
            memory.append(db, "finding", finding_id, evidence)
    return {"status": "FINDING_RECORDED", "finding_id": finding_id, "evidence_id": evidence_id}


def select_policy(firewall, db, protection, checkout, contract):
    manifest = firewall._active(db, protection)
    if manifest is None:
        return "inactive", None
    if manifest["category"] != policy_rules.CATEGORY:
        return "unsupported", None
    if not firewall._artifact_matches(checkout, protection, manifest):
        return "artifact_invalid", None
    if policy_rules.conflicts(manifest["policy"], contract):
        return "conflict", None
    return "eligible", manifest


def policy_result(firewall, db, protection, selection, item, result):
    state, manifest = selection
    paths = result.pop("policy_paths", ())
    if manifest is None or "observed_head_sha" not in result:
        return {"id": protection, "state": state if manifest is None else "unverified", "recurrence": False}
    source = firewall._events(db, manifest["source_finding_id"], "finding")[0]["data"]
    keys = [policy_rules.failure_key(item["project"], manifest["policy"], path) for path in paths]
    recurrence = (item["task_id"] != source["task_id"] and item["head_sha"] != source["head_sha"]
                  and bool(set(keys).intersection(source["failure_keys"])))
    return {"id": protection, "state": "violated" if paths else "clear", "recurrence": recurrence,
            "source_finding_id": manifest["source_finding_id"], "failure_keys": keys,
            "source_evidence_id": source["evidence_id"]}


def project_selection(firewall, db, checkout, contract):
    """Resolve the operator's active local task policies in stable order."""
    selections = {}
    digests = {}
    for subject, data in db.execute(
        "SELECT subject, data FROM events WHERE kind = 'protection' ORDER BY subject"
    ):
        if json.loads(data)["category"] != policy_rules.CATEGORY:
            continue
        state, manifest = select_policy(firewall, db, subject, checkout, contract)
        if state == "inactive":
            history = firewall._events(db, subject, "protection")
            if firewall._protection_state(history)["kind"] != "protection_approved":
                continue
            state = "unsupported"
        selections[subject] = (state, manifest)
        rule = manifest["policy"] if manifest else {}
        if rule.get("kind") == "blob_sha256":
            digests.setdefault(rule["path"], set()).add(rule["digest"])
    for subject, (state, manifest) in selections.items():
        rule = manifest["policy"] if manifest else {}
        if rule.get("kind") == "blob_sha256" and len(digests[rule["path"]]) > 1:
            selections[subject] = ("conflict", None)
    return selections


def verify(memory, submission, digest, git, env, *, protection=None, artifact_checkout=None,
           after_correction=None, project_policies=False):
    item = validate(submission)
    if (item["project"] != memory.repository or bool(protection or project_policies) != bool(artifact_checkout)
            or project_policies and protection or after_correction and not (protection or project_policies) or protection is not None and
            not re.fullmatch(r"p-[0-9a-f]{64}", protection)):
        raise ValueError("Invalid operator policy selection or project")
    event = "task-event-" + item["event_id"]
    agent_event = "agent-event-" + item["event_id"]
    identity = [item, digest]
    if protection:
        identity.extend([protection, uuid_text(after_correction) if after_correction else None])
    if project_policies:
        identity.extend(["project-task-policies", uuid_text(after_correction) if after_correction else None])
    fingerprint = identifier("submission", identity)
    firewall = Firewall(memory)
    with memory.transaction() as db:
        contract = active_contract(memory, db, item["task_id"], digest)
        prior = memory.history(db, event)
        selection = (select_policy(firewall, db, protection, artifact_checkout, contract)
                     if protection and not prior else ("not_selected", None))
        selections = (project_selection(firewall, db, artifact_checkout, contract)
                      if project_policies and not prior else {})
    if not prior:
        try:
            manifest = selection[1]
            result = inspect(contract, git, item["head_sha"], env,
                             **({"policy": manifest["policy"]} if manifest else {}),
                             **({"policies": {key: entry[1]["policy"] for key, entry in selections.items()
                                              if entry[1]}} if project_policies else {}))
        except (GitUnavailable, OSError, ValueError):
            result = {"status": "ERROR", "reason": "git_evidence_unavailable"}
    with memory.transaction(write=True) as db:
        active_contract(memory, db, item["task_id"], digest)
        prior = memory.history(db, event)
        if prior:
            if prior[0]["data"]["fingerprint"] != fingerprint:
                raise ValueError("Conflicting task event")
            return {"status": "INCONCLUSIVE", "reason": "duplicate_event"}
        if memory.history(db, agent_event):
            raise ValueError("Agent event already used by another verifier")
        task_status = result["status"]
        paths = result.pop("policy_set_paths", {})
        policies = []
        if project_policies:
            current_set = project_selection(firewall, db, artifact_checkout, contract)
            for key in sorted(selections.keys() | current_set.keys()):
                current = current_set.get(key, ("inactive", None))
                if current != selections.get(key) and current[1] is not None:
                    current = ("unverified", None)
                observation = {**result, "policy_paths": paths.get(key, ())}
                policies.append(policy_result(firewall, db, key, current, item, observation))
            violations = [entry for entry in policies if entry["state"] == "violated"]
            unresolved = [entry for entry in policies if entry["state"] not in {"clear", "violated"}]
            policy = (violations[0] if len(violations) == 1 and not unresolved else
                      unresolved[0] if unresolved else
                      {"state": "violated" if violations else "clear",
                       "recurrence": any(entry["recurrence"] for entry in violations)})
            result.pop("policy_paths", None)
            if after_correction:
                parent = recorded_report(memory, db, "agent-event-" + after_correction)
                protection = ((parent or {}).get("protection") or {}).get("id")
                if not protection or not any(entry["id"] == protection for entry in policies):
                    raise ValueError("Correction protection unavailable in the selected set")
            elif len(violations) == 1 and not unresolved:
                protection = policy["id"]
        elif protection:
            current = select_policy(firewall, db, protection, artifact_checkout, contract)
            if current != selection:
                selection = (current[0] if current[1] is None else "unverified", None)
            policy = policy_result(firewall, db, protection, selection, item, result)
        else:
            policy = {"state": "not_selected", "recurrence": False}
        if after_correction:
            link_correction(memory, db, item, after_correction, protection, rule=RULE)
        state = policy["state"]
        if state == "violated" or any(entry["state"] == "violated" for entry in policies):
            result["status"] = "POLICY_VIOLATION"
        elif state in {"artifact_invalid", "conflict", "unsupported"} and task_status == "VERIFIED":
            result["status"] = "ERROR"
        elif state in {"unverified", "inactive"} and task_status == "VERIFIED":
            result["status"] = "INCONCLUSIVE"
        report = {"version": 1, "rule": RULE, "task_id": item["task_id"], "event_id": item["event_id"],
                  "project": item["project"], "pr": item["pr"], "agent": item["agent"],
                  "requested_head_sha": item["head_sha"], "contract_digest": digest,
                  "agent_declaration": {"agent": item["agent"], "complete": True},
                  "task_status": task_status, "policy": policy, **result}
        report["evidence"] = ({"base_sha": result["base_sha"], "head_sha": result["observed_head_sha"]}
                              if "observed_head_sha" in result else None)
        if project_policies:
            report["policies"] = policies
        report["protection"] = {"id": protection} if protection else None
        report["operator_action"] = ("none" if result["status"] == "VERIFIED" else
                                     "review_policy_violation" if state == "violated" else
                                     "review_task_evidence")
        if after_correction:
            report["correction"] = {"authorized_event": after_correction, "verified": result["status"] == "VERIFIED"}
        report["evidence_id"] = identifier("task-evidence", report)
        memory.append(db, "task_verified", event, {"fingerprint": fingerprint, "report": report})
        memory.append(db, "agent_submission", agent_event, {"fingerprint": fingerprint, "journal": 2})
        return record_report(memory, db, agent_event, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--store", required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("approve").add_argument("--checkout", required=True)
    check = actions.add_parser("verify")
    check.add_argument("--checkout", required=True)
    check.add_argument("--digest", required=True)
    check.add_argument("--protection")
    check.add_argument("--artifact-checkout")
    check.add_argument("--after-correction")
    capture = actions.add_parser("finding")
    capture.add_argument("--event-id", required=True)
    failure = capture.add_mutually_exclusive_group(required=True)
    failure.add_argument("--criterion-index", type=int)
    failure.add_argument("--violation-index", type=int)
    disable = actions.add_parser("revoke")
    disable.add_argument("--task-id", required=True)
    disable.add_argument("--digest", required=True)
    args = parser.parse_args()
    try:
        memory = Memory(args.store, args.repository)
        if args.action == "approve":
            result = approve(memory, read_json(32768), GitObjects(args.checkout))
        elif args.action == "revoke":
            result = revoke(memory, uuid_text(args.task_id), args.digest)
        elif args.action == "finding":
            result = capture_finding(memory, args.event_id, criterion_index=args.criterion_index,
                                     violation_index=args.violation_index)
        else:
            result = verify(memory, read_json(4096), args.digest, GitObjects(args.checkout), os.environ,
                            protection=args.protection, artifact_checkout=args.artifact_checkout,
                            after_correction=args.after_correction)
    except Exception:
        result = {"status": "ERROR", "reason": "task_contract_or_evidence_rejected"}
    print(json.dumps(result, ensure_ascii=True))
    return {"APPROVED": 0, "REVOKED": 0, "VERIFIED": 0, "FINDING_RECORDED": 0, "INCOMPLETE": 2,
            "POLICY_VIOLATION": 2}.get(result["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
