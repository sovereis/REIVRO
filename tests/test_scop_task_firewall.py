from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from uuid import uuid4

import pytest

from server import scop_task_verification as task
from server.scop_agent_feedback import checked_feedback
from server.scop_firewall import Firewall
from server.scop_firewall_memory import FirewallError, Memory
from test_scop_task_verification import PROJECT, ROOT, commit, run_git

MANIFEST = ROOT / "benchmarks/task-firewall/scenarios-v1.json"


def task_case(root, memory, name, *, kind="exists", initial=None, expected="a" * 64, agent="codex",
              allowed=None, protected=()):
    checkout = root / name
    checkout.mkdir(parents=True)
    run_git(checkout, "-c", "init.templateDir=", "init", "-q")
    (checkout / "marker.txt").write_text(name)
    if initial is not None:
        (checkout / "evidence.txt").write_text(initial)
    base = commit(checkout)
    git = task.GitObjects(checkout)
    criterion = {"kind": kind, "path": "evidence.txt"}
    if kind == "blob_sha256":
        criterion["digest"] = expected
    if kind == "manual":
        criterion.pop("path")
    contract = {"version": 1, "project": PROJECT, "task_id": str(uuid4()), "base_sha": base,
                "objective": "fixture", "allowed_paths": ["evidence.txt"] if allowed is None else allowed,
                "protected_paths": list(protected), "criteria": [criterion]}
    digest = task.approve(memory, contract, git)["digest"]
    claim = {"version": 1, "agent": agent, "project": PROJECT, "task_id": contract["task_id"],
             "event_id": str(uuid4()), "pr": 1, "head_sha": commit(checkout)}
    return git, digest, claim


def capture(memory, report, artifact_checkout, **selection):
    finding = task.capture_finding(memory, report["event_id"], **selection)["finding_id"]
    firewall = Firewall(memory)
    with pytest.raises(FirewallError, match="Explicitly confirm"):
        firewall.propose(finding)
    firewall.decide_finding(finding, "confirm", "Operator verified the cited revision")
    protection = firewall.propose(finding)["protection_id"]
    firewall.decide_protection(protection, "approve", "Operator approved reusable policy")
    exported = firewall.export(protection, artifact_checkout)
    manifest = Path(exported["path"])
    assert sha256(manifest.read_bytes()).hexdigest() == exported["artifact_sha256"]
    if not (artifact_checkout / ".git").exists():
        run_git(artifact_checkout, "-c", "init.templateDir=", "init", "-q")
    relative = manifest.relative_to(artifact_checkout).as_posix()
    run_git(artifact_checkout, "add", "--", relative)
    assert run_git(artifact_checkout, "show", ":" + relative) == manifest.read_text().strip()
    return protection, manifest


def workflow(root):
    memory = Memory(root / "memory", PROJECT)
    memory.initialize()
    artifact_checkout = root / "artifacts"
    artifact_checkout.mkdir()
    original_git, original_digest, original_claim = task_case(root, memory, "original")
    started = perf_counter_ns()
    original = task.verify(memory, original_claim, original_digest, original_git, {})
    rows = [("original_incomplete", original, perf_counter_ns() - started)]
    protection, manifest = capture(memory, original, artifact_checkout, criterion_index=0)
    guarded = {"protection": protection, "artifact_checkout": artifact_checkout}
    git, digest, claim = task_case(root, memory, "new-task", kind="exists", agent="cursor")
    started = perf_counter_ns()
    repeat = task.verify(memory, claim, digest, git, {}, **guarded)
    rows.append(("cross_task_recurrence", repeat, perf_counter_ns() - started))
    assert repeat["policy"]["recurrence"]
    assert original["agent"] != repeat["agent"]
    assert repeat["policy"]["source_evidence_id"] == original["evidence_id"]
    assert repeat["operator_action"] == "review_policy_violation"

    (Path(git.checkout) / "evidence.txt").write_text("approved correction")
    correction = {**claim, "event_id": str(uuid4()), "head_sha": commit(git.checkout)}
    with pytest.raises(ValueError, match="authorization"):
        task.verify(memory, correction, digest, git, {}, after_correction=claim["event_id"], **guarded)
    approved = checked_feedback(memory, repeat, claim["event_id"], authorize=True)
    assert approved["feedback"]["decision"] == "correction_authorized"
    started = perf_counter_ns()
    fixed = task.verify(memory, correction, digest, git, {}, after_correction=claim["event_id"], **guarded)
    rows.append(("authorized_correction", fixed, perf_counter_ns() - started))
    assert fixed["correction"]["verified"]
    assert task.verify(memory, correction, digest, git, {}, after_correction=claim["event_id"],
                       **guarded)["reason"] == "duplicate_event"

    manifest.write_bytes(manifest.read_bytes() + b" ")
    started = perf_counter_ns()
    tampered = task.verify(memory, {**correction, "event_id": str(uuid4())}, digest, git, {}, **guarded)
    rows.append(("artifact_tampered", tampered, perf_counter_ns() - started))
    Firewall(memory).decide_protection(protection, "revoke", "Operator revoked")
    started = perf_counter_ns()
    revoked = task.verify(memory, {**correction, "event_id": str(uuid4())}, digest, git, {}, **guarded)
    rows.append(("revoked", revoked, perf_counter_ns() - started))
    return rows


def test_task_firewall_e2e(tmp_path):
    rows = workflow(tmp_path)
    assert {name: (result["status"], result["policy"]["recurrence"]) for name, result, _ in rows} == {
        case["id"]: (case["status"], case["recurrence"]) for case in json.loads(MANIFEST.read_text())["cases"]
    }


def test_scope_similarity_conflict_revision_and_tenant(tmp_path):
    memory = Memory(tmp_path / "memory", PROJECT)
    memory.initialize()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    git, digest, claim = task_case(tmp_path, memory, "scope", initial="original")
    (Path(git.checkout) / "outside-one").write_text("fixture")
    report = task.verify(memory, {**claim, "head_sha": commit(git.checkout)}, digest, git, {})
    protection, _ = capture(memory, report, artifacts, violation_index=0)
    guarded = {"protection": protection, "artifact_checkout": artifacts}
    other, other_digest, other_claim = task_case(tmp_path, memory, "another-scope",
                                                initial="original", allowed=["evidence.txt", "outside-two"])
    (Path(other.checkout) / "outside-two").write_text("fixture")
    observed = task.verify(memory, {**other_claim, "head_sha": commit(other.checkout)}, other_digest,
                           other, {}, **guarded)
    assert observed["policy"]["state"] == "violated" and not observed["policy"]["recurrence"]
    with pytest.raises(ValueError):
        task.verify(memory, {**other_claim, "project": "foreign/repo"}, other_digest, other, {}, **guarded)
    assert task.verify(memory, {**other_claim, "event_id": str(uuid4()), "head_sha": "f" * 40}, other_digest, other, {},
                       **guarded)["policy"]["state"] == "unverified"

    git, digest, claim = task_case(tmp_path, memory, "pinned", kind="blob_sha256", initial="original")
    original = task.verify(memory, claim, digest, git, {})
    pinned, _ = capture(memory, original, artifacts, criterion_index=0)
    other, other_digest, other_claim = task_case(tmp_path, memory, "conflict", kind="blob_sha256",
                                                expected="b" * 64, initial="original")
    result = task.verify(memory, other_claim, other_digest, other, {}, protection=pinned,
                         artifact_checkout=artifacts)
    assert result["policy"]["state"] == "conflict" and result["status"] != "VERIFIED"
    assert Firewall(memory).run(pinned, artifacts, f"https://github.com/{PROJECT}/pull/1",
                                True)["status"] == "INAPPLICABLE"


def test_concurrent_replay_and_policy_revocation(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory", PROJECT)
    memory.initialize()
    git, digest, claim = task_case(tmp_path, memory, "original")
    report = task.verify(memory, claim, digest, git, {})
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    protection, _ = capture(memory, report, artifacts, criterion_index=0)
    guarded = {"protection": protection, "artifact_checkout": artifacts}
    git, digest, claim = task_case(tmp_path, memory, "concurrent", initial="valid")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: task.verify(memory, claim, digest, git, {}, **guarded), range(2)))
    assert sorted(result["status"] for result in results) == ["INCONCLUSIVE", "VERIFIED"]
    inspect = task.inspect

    def during(*args, **kwargs):
        result = inspect(*args, **kwargs)
        Firewall(memory).decide_protection(protection, "revoke", "Operator revoked while reading")
        return result

    monkeypatch.setattr(task, "inspect", during)
    report = task.verify(memory, {**claim, "event_id": str(uuid4())}, digest, git, {}, **guarded)
    assert report["task_status"] == "VERIFIED" and report["status"] == "INCONCLUSIVE"
    assert report["policy"]["state"] == "inactive"


def test_task_firewall_benchmark(tmp_path):
    output = os.getenv("REIVRO_TASK_FIREWALL_OUTPUT")
    if not output:
        pytest.skip("Set REIVRO_TASK_FIREWALL_OUTPUT for benchmark")
    manifest = json.loads(MANIFEST.read_text())
    rows = []
    for index in range(manifest["repetitions"]):
        for case, (name, result, elapsed) in zip(manifest["cases"], workflow(tmp_path / str(index)), strict=True):
            assert case["id"] == name
            rows.append({"scenario": name, "status": result["status"], "expected": case["status"],
                         "recurrence": result["policy"]["recurrence"], "expected_recurrence": case["recurrence"],
                         "truth_policy_violation": case["truth_policy_violation"],
                         "elapsed_ms": round(elapsed / 1_000_000, 3)})
    times = sorted(row["elapsed_ms"] for row in rows)
    passed = sum(row["status"] == row["expected"] and row["recurrence"] == row["expected_recurrence"] for row in rows)
    report = {"code_sha": run_git(ROOT, "rev-parse", "HEAD"), "matched": passed,
              "incomplete": sum(row["status"] == "INCOMPLETE" for row in rows),
              "policy_violations": sum(row["status"] == "POLICY_VIOLATION" for row in rows),
              "confirmed_recurrences": sum(row["recurrence"] for row in rows),
              "false_positive": sum(row["truth_policy_violation"] is False and row["status"] == "POLICY_VIOLATION" for row in rows),
              "false_negative": sum(row["truth_policy_violation"] is True and row["status"] == "VERIFIED" for row in rows),
              "inconclusive": sum(row["status"] == "INCONCLUSIVE" for row in rows),
              "median_ms": round(median(times), 3), "p95_ms": times[(95 * len(times) + 99) // 100 - 1],
              "blocking_exercised": False, "results": rows}
    Path(output).write_text(json.dumps(report, indent=2) + "\n")
    assert passed == len(rows)


def test_protected_file_policy_and_task_specific_change(tmp_path):
    memory = Memory(tmp_path / "memory", PROJECT)
    memory.initialize()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    git, digest, claim = task_case(tmp_path, memory, "protected", kind="changed", initial="original",
                                   protected=["evidence.txt"])
    unchanged = task.verify(memory, claim, digest, git, {})
    with pytest.raises(FirewallError, match="task-specific"):
        task.capture_finding(memory, claim["event_id"], criterion_index=0)
    (Path(git.checkout) / "evidence.txt").write_text("not authorized")
    report = task.verify(memory, {**claim, "event_id": str(uuid4()), "head_sha": commit(git.checkout)},
                         digest, git, {})
    assert unchanged["status"] == "INCOMPLETE" and report["status"] == "POLICY_VIOLATION"
    protection, _ = capture(memory, report, artifacts, violation_index=0)
    other, other_digest, other_claim = task_case(tmp_path, memory, "next-protected", initial="original")
    (Path(other.checkout) / "evidence.txt").write_text("again")
    result = task.verify(memory, {**other_claim, "head_sha": commit(other.checkout)}, other_digest, other,
                         {}, protection=protection, artifact_checkout=artifacts)
    assert result["task_status"] == "VERIFIED"
    assert result["status"] == "POLICY_VIOLATION" and result["policy"]["recurrence"]
