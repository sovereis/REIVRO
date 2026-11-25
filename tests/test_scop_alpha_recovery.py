import shutil
from uuid import uuid4

import pytest

from server import scop_task_verification as task
from server.scop_agent_feedback import checked_feedback
from server.scop_firewall import Firewall
from server.scop_firewall_memory import Memory
from test_scop_task_firewall import PROJECT, capture, task_case


def test_clean_restore_preserves_results_approval_and_revocation(tmp_path):
    original = Memory(tmp_path / "original", PROJECT)
    original.initialize()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    git, digest, claim = task_case(tmp_path, original, "source")
    report = task.verify(original, claim, digest, git, {})
    protection, _ = capture(original, report, artifacts, criterion_index=0)
    Firewall(original).export(protection, original.directory)
    # No open writers. Copy the entire private directory, preserving owner and modes.
    shutil.copytree(original.directory, tmp_path / "restored")
    restored = Memory(tmp_path / "restored", PROJECT)
    assert checked_feedback(restored, None, claim["event_id"]) == report
    git, digest, claim = task_case(tmp_path, restored, "candidate", initial="present")
    def verify():
        return task.verify(restored, {**claim, "event_id": str(uuid4())}, digest, git, {},
                           project_policies=True, artifact_checkout=restored.directory)
    assert verify()["status"] == "VERIFIED"
    path = restored.directory / ".reivro/protections" / (protection + ".json")
    path.unlink()
    assert verify()["status"] == "ERROR"
    Firewall(restored).export(protection, restored.directory)
    path.write_bytes(path.read_bytes() + b" ")
    assert verify()["status"] == "ERROR"
    path.rename(path.with_suffix(".damaged"))
    Firewall(restored).export(protection, restored.directory)
    assert verify()["status"] == "VERIFIED"
    Firewall(restored).decide_protection(protection, "revoke", "operator revoked")
    shutil.copytree(restored.directory, tmp_path / "restored-again")
    again = Memory(tmp_path / "restored-again", PROJECT)
    with again.transaction() as db:
        assert Firewall(again)._active(db, protection) is None


def test_interruption_before_result_can_retry(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "private", PROJECT)
    memory.initialize()
    git, digest, claim = task_case(tmp_path, memory, "candidate", initial="present")
    inspect = task.inspect
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(task, "inspect", interrupt)
    with pytest.raises(KeyboardInterrupt):
        task.verify(memory, claim, digest, git, {})
    monkeypatch.setattr(task, "inspect", inspect)
    report = task.verify(memory, claim, digest, git, {})
    assert report["status"] == "VERIFIED"
    assert checked_feedback(memory, None, claim["event_id"]) == report
