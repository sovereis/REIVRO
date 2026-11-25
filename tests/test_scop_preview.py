import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from server import scop_task_verification as task
from server.scop_firewall import Firewall
from server.scop_firewall_memory import Memory
from test_scop_task_firewall import PROJECT, capture, task_case

CLI = Path(__file__).resolve().parents[1] / "reivro"


def test_disposable_demo_and_configuration_error(tmp_path):
    env = {"PATH": os.defpath, "HOME": str(tmp_path)}
    for _ in range(2):
        result = subprocess.run([CLI, "--json", "demo"], cwd=tmp_path, env=env,
                                capture_output=True, check=True, timeout=30)
        report = json.loads(result.stdout)
        assert report["status"] == "DEMO_PASSED"
        assert report["synthetic"] and report["confirmed_recurrence"]
        assert len(report["steps"]) == 13
    result = subprocess.run([CLI, "--json", "doctor"], cwd=tmp_path, env=env,
                            capture_output=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "ERROR"
    assert not list(tmp_path.iterdir())


def test_project_policy_set_and_artifact_recovery(tmp_path):
    memory = Memory(tmp_path / "memory", PROJECT)
    memory.initialize()
    (tmp_path / "artifacts").mkdir()
    git, digest, claim = task_case(tmp_path, memory, "initial")
    report = task.verify(memory, claim, digest, git, {})
    first, _ = capture(memory, report, tmp_path / "artifacts", criterion_index=0)
    manifest = Path(Firewall(memory).export(first, memory.directory)["path"])
    git, digest, claim = task_case(tmp_path, memory, "another", kind="blob_sha256", expected="1" * 64)
    report = task.verify(memory, claim, digest, git, {})
    second, _ = capture(memory, report, tmp_path / "artifacts", criterion_index=0)
    Firewall(memory).export(second, memory.directory)

    def verify():
        return task.verify(memory, {**claim, "event_id": str(uuid4())}, digest, git, {},
                           project_policies=True, artifact_checkout=memory.directory)

    git, digest, claim = task_case(tmp_path, memory, "candidate", initial="present")
    result = verify()
    assert result["status"] == "POLICY_VIOLATION"
    assert {item["id"]: item["state"] for item in result["policies"]} == {first: "clear", second: "violated"}
    Firewall(memory).decide_protection(second, "revoke", "operator decision")
    assert verify()["status"] == "VERIFIED"
    manifest.unlink()
    assert verify()["status"] == "ERROR"
    Firewall(memory).export(first, memory.directory)
    assert verify()["status"] == "VERIFIED"


def test_conflicting_approved_project_policies_are_inconclusive(tmp_path):
    memory = Memory(tmp_path / "memory", PROJECT)
    memory.initialize()
    (tmp_path / "artifacts").mkdir()
    for character in ("a", "b"):
        git, digest, claim = task_case(tmp_path, memory, character, kind="blob_sha256", expected=character * 64)
        report = task.verify(memory, claim, digest, git, {})
        protection, _ = capture(memory, report, tmp_path / "artifacts", criterion_index=0)
        Firewall(memory).export(protection, memory.directory)
    git, digest, claim = task_case(tmp_path, memory, "candidate", initial="present")
    result = task.verify(memory, claim, digest, git, {}, project_policies=True,
                         artifact_checkout=memory.directory)
    assert result["status"] == "ERROR"
    assert result["task_status"] == "VERIFIED"
    assert [entry["state"] for entry in result["policies"]] == ["conflict", "conflict"]


def test_project_policy_revocation_during_verification(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory", PROJECT)
    memory.initialize()
    (tmp_path / "artifacts").mkdir()
    git, digest, claim = task_case(tmp_path, memory, "source")
    initial = task.verify(memory, claim, digest, git, {})
    protection, _ = capture(memory, initial, tmp_path / "artifacts", criterion_index=0)
    firewall = Firewall(memory)
    firewall.export(protection, memory.directory)
    git, digest, claim = task_case(tmp_path, memory, "candidate", initial="present")
    inspect = task.inspect

    def revoke_after_inspection(*args, **kwargs):
        result = inspect(*args, **kwargs)
        firewall.decide_protection(protection, "revoke", "operator decision during verification")
        return result

    monkeypatch.setattr(task, "inspect", revoke_after_inspection)
    result = task.verify(memory, claim, digest, git, {}, project_policies=True,
                         artifact_checkout=memory.directory)
    assert result["status"] == "INCONCLUSIVE"
    assert result["policies"][0]["state"] == "inactive"
