from hashlib import sha256
import json
import os
from pathlib import Path
from statistics import median
import subprocess
from time import perf_counter_ns
from uuid import uuid4

import pytest

from server import scop_task_verification as task
from server.scop_firewall_memory import Memory

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/tasks/scenarios-v1.json"
CASES = json.loads(MANIFEST.read_text())["cases"]
PROJECT = "example/task"


def run_git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "-c", "user.name=Fixture",
         "-c", "user.email=fixture@example.invalid", *args], text=True,
    ).strip()


def commit(repo):
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "--allow-empty", "-qm", "Synthetic task")
    return run_git(repo, "rev-parse", "HEAD")


def prepare(path, name):
    repo = path / "checkout"
    repo.mkdir(parents=True)
    run_git(repo, "-c", "init.templateDir=", "init", "-q")
    (repo / "required.py").write_text("value = 1\n")
    (repo / "protected.txt").write_text("protected\n")
    base = commit(repo)
    git = task.GitObjects(repo)
    memory = Memory(path / "private", PROJECT)
    memory.initialize()
    value = {
        "version": 1, "project": PROJECT, "task_id": str(uuid4()), "base_sha": base,
        "objective": "Private objective: do not echo this",
        "allowed_paths": ["required.py", "evidence.txt"],
        "protected_paths": ["protected.txt"],
        "criteria": [{"kind": "exists", "path": "required.py"}, {"kind": "changed", "path": "required.py"},
                     {"kind": "blob_sha256", "path": "evidence.txt",
                      "digest": sha256(b"approved bytes\n").hexdigest()}],
    }
    if name == "manual_criterion":
        value["criteria"].append({"kind": "manual"})
    digest = task.approve(memory, value, git)["digest"]
    if name == "missing":
        (repo / "required.py").unlink()
    elif name != "unchanged":
        (repo / "required.py").write_text("value = 2\n")
    if name not in {"partial", "unchanged"}:
        (repo / "evidence.txt").write_text("untrusted claim\n" if name == "false_evidence" else "approved bytes\n")
    if name == "protected":
        (repo / "protected.txt").write_text("different\n")
    if name == "out_of_scope":
        (repo / "outside.txt").write_text("outside\n")
    head = commit(repo)
    claim = {"version": 1, "agent": "codex", "project": PROJECT, "task_id": value["task_id"],
             "event_id": str(uuid4()), "pr": 1, "head_sha": "f" * 40 if name == "head_diverged" else head}
    return memory, git, claim, digest


def evaluate(prepared, name):
    memory, git, claim, digest = prepared
    if name == "contract_changed":
        with memory.transaction(write=True) as db:
            event, = memory.history(db, task.subject(claim["task_id"]))
            event["data"]["contract"]["objective"] = "modified after approval"
            db.execute("update events set data = ? where subject = ?",
                       (json.dumps(event["data"]), task.subject(claim["task_id"])))
        with pytest.raises(ValueError, match="digest mismatch"):
            task.verify(memory, claim, digest, git, {})
        return {"status": "ERROR"}
    return task.verify(memory, claim, digest, git, {})


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_static_task_contract(case, tmp_path):
    result = evaluate(prepare(tmp_path, case["id"]), case["id"])
    assert result["status"] == case["expected"]
    dumped = json.dumps(result)
    assert all(secret not in dumped for secret in ("Private objective", "approved bytes", "required.py"))


def test_duplicate_recurrence_revoke_and_agent_approval_rejected(tmp_path):
    memory, git, claim, digest = prepare(tmp_path, "partial")
    with pytest.raises(ValueError):
        task.verify(memory, {**claim, "approve": True}, digest, git, {})
    first = task.verify(memory, claim, digest, git, {})
    assert task.verify(memory, claim, digest, git, {})["reason"] == "duplicate_event"
    (Path(git.checkout) / "required.py").write_text("value = 3\n")
    repeated = task.verify(memory, {**claim, "event_id": str(uuid4()),
                                   "head_sha": commit(git.checkout)}, digest, git, {})
    assert first["criteria"] == repeated["criteria"] and first["status"] == repeated["status"] == "INCOMPLETE"
    task.revoke(memory, claim["task_id"], digest)
    with pytest.raises(ValueError, match="active operator approval"):
        task.verify(memory, {**claim, "event_id": str(uuid4())}, digest, git, {})


def test_symlink_cannot_supply_required_evidence(tmp_path):
    memory, git, claim, digest = prepare(tmp_path, "complete")
    path = Path(git.checkout) / "evidence.txt"
    path.unlink()
    path.symlink_to("required.py")
    result = task.verify(memory, {**claim, "head_sha": commit(git.checkout)}, digest, git, {})
    assert result["status"] == "INCOMPLETE"


def test_cloud_evidence_pinned_and_regression_never_passes(monkeypatch):
    key = str(uuid4())
    base, head = "a" * 40, "b" * 40
    binding = {"repository_id": 10, "run_id": key, "outcome": "OBSERVED"}
    run = {"id": key, "head_sha": head, "base_sha": base, "outcome": "OBSERVED",
           "report": {"repository": PROJECT, "head_sha": head, "base_sha": base, "status": "PASS"}}

    class MemoryFixture:
        def __init__(self, ref, key, token):
            assert ref == task.STAGING

        def read_run(self, repository_id, run_id):
            assert (repository_id, run_id) == (10, key)
            return {"run": run}

    monkeypatch.setattr(task, "StagingMemory", MemoryFixture)
    env = {"REIVRO_STAGING_REF": task.STAGING, "REIVRO_PUBLISHABLE_KEY": "fixture",
           "REIVRO_AGENT_READER_JWT": "fixture"}
    contract = {"project": PROJECT, "base_sha": base}
    assert task.cloud_evidence(binding, contract, head, env) is True
    run["report"]["status"] = "REGRESSION_DETECTED"
    assert task.cloud_evidence(binding, contract, head, env) is False
    assert task.cloud_evidence(binding, contract, head, {}) is None


def test_task_benchmark(tmp_path):
    output = os.getenv("REIVRO_TASK_BENCHMARK_OUTPUT")
    if not output:
        pytest.skip("Set REIVRO_TASK_BENCHMARK_OUTPUT to record measurements")
    rows = []
    for index in range(3):
        for case in CASES:
            prepared = prepare(tmp_path / f"{index}-{case['id']}", case["id"])
            start = perf_counter_ns()
            status = evaluate(prepared, case["id"])["status"]
            rows.append({**case, "status": status, "repetition": index + 1,
                         "elapsed_ms": round((perf_counter_ns() - start) / 1_000_000, 3)})
    scored = [row for row in rows if row["truth_incomplete"] is not None]
    latency = sorted(row["elapsed_ms"] for row in rows)
    report = {
        "version": 1, "code_sha": run_git(ROOT, "rev-parse", "HEAD"),
        "manifest_sha256": sha256(MANIFEST.read_bytes()).hexdigest(), "repetitions": 3,
        "source": "synthetic tasks on local Git commits",
        "matched": sum(row["status"] == row["expected"] for row in rows),
        "incomplete_detected": sum(row["truth_incomplete"] and row["status"] == "INCOMPLETE" for row in scored),
        "false_positive": sum(not row["truth_incomplete"] and row["status"] == "INCOMPLETE" for row in scored),
        "false_negative": sum(row["truth_incomplete"] and row["status"] == "VERIFIED" for row in scored),
        "inconclusive": sum(row["status"] == "INCONCLUSIVE" for row in rows),
        "scope_violations": sum(row["status"] == "POLICY_VIOLATION" for row in rows),
        "median_ms": round(median(latency), 3), "p95_ms": latency[(95 * len(latency) + 99) // 100 - 1],
        "results": rows,
    }
    Path(output).write_text(json.dumps(report, indent=2) + "\n")
    assert report["matched"] == len(rows)


def test_revocation_during_inspection_cannot_write_favorable_result(tmp_path, monkeypatch):
    memory, git, claim, digest = prepare(tmp_path, "complete")
    inspect = task.inspect

    def revoke_during(*args):
        result = inspect(*args)
        assert result["status"] == "VERIFIED"
        task.revoke(memory, claim["task_id"], digest)
        return result

    monkeypatch.setattr(task, "inspect", revoke_during)
    with pytest.raises(ValueError, match="active operator approval"):
        task.verify(memory, claim, digest, git, {})
    with memory.transaction() as db:
        assert not memory.history(db, "task-event-" + claim["event_id"])


def test_mode_only_change_does_not_meet_required_content_change(tmp_path):
    memory, git, claim, digest = prepare(tmp_path, "complete")
    path = Path(git.checkout) / "required.py"
    path.write_text("value = 1\n")
    path.chmod(0o755)
    report = task.verify(memory, {**claim, "head_sha": commit(git.checkout)}, digest, git, {})
    assert report["status"] == "INCOMPLETE"
    assert report["criteria"][1]["outcome"] == "unmet"
