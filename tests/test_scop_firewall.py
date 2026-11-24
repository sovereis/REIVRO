"""Complete local firewall flow with GitHub fixtures and the real compiler."""
import base64
from hashlib import sha1
import json
from pathlib import Path
import subprocess
import sys

import pytest

from server import scop_firewall as firewall, scop_verify_syntax as syntax
from server.scop_firewall_memory import FirewallError, Memory


ROOT = "https://github.com/example/fixture"
API = "https://api.github.com/repos/example/fixture"
REPO = "example/fixture"
FIRST, SECOND, CLEAN, MISSING, ERROR = (f"{ROOT}/pull/{number}" for number in range(1, 6))


def blob(path, line):
    raw = (line + "\n").encode()
    digest = sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()
    return {"path": path, "sha": digest, "size": len(raw), "type": "file",
            "encoding": "base64", "content": base64.b64encode(raw).decode()}


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    store = tmp_path / "memory"
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    memory = Memory(store, REPO)
    memory.initialize()
    responses = {}
    for number, before, after, path in (
        (1, "x = 1", "x = )", "first.py"),
        (2, "def greeting(): pass", "def greeting(): )", "future.py"),
        (3, "value = 1", "value = 2", "clean.py"),
        (4, "x = 2", "x = (", "missing.py"),
    ):
        base, head = f"{number:040x}", f"{number + 100:040x}"
        endpoint = f"{API}/pulls/{number}"
        old, new = blob(path, before), blob(path, after)
        responses[endpoint] = {"html_url": f"{ROOT}/pull/{number}", "base": {"sha": base},
                               "head": {"sha": head}, "changed_files": 1}
        responses[endpoint + "/files?per_page=100&page=1"] = [{
            "filename": path, "sha": new["sha"], "status": "modified", "additions": 1,
            "deletions": 1, "patch": None if number == 4 else f"@@ -1 +1 @@\n-{before}\n+{after}",
        }]
        responses[f"{API}/contents/{path}?ref={base}"] = old
        responses[f"{API}/contents/{path}?ref={head}"] = new
    calls = []

    def fetch(url, deadline):
        calls.append(url)
        if url not in responses:
            raise syntax.github._Unavailable("GitHub fixture unavailable")
        return responses[url]

    monkeypatch.setattr(syntax.github, "fetch_json", fetch)
    return firewall.Firewall(memory), checkout, calls


def approved(service, checkout):
    original = service.analyze(FIRST, True)
    finding, = original["finding_ids"]
    service.decide_finding(finding, "confirm", "Reviewed the exact pinned syntax error")
    proposal = service.propose(finding)
    protection = proposal["protection_id"]
    service.decide_protection(protection, "approve", "Reviewed scope and syntax trigger")
    return finding, protection, Path(service.export(protection, checkout)["path"])


def test_cycle_through_cli_with_git_versioned_artifact(scenario, monkeypatch, capsys):
    service, checkout, _ = scenario

    def cli(*args, exit_code=0):
        monkeypatch.setattr(sys, "argv", ["firewall", "--repository", REPO, "--store",
                                        str(service.memory.directory), *args])
        assert firewall.main() == exit_code
        return json.loads(capsys.readouterr().out)

    first = cli("analyze", FIRST, "--github-read", exit_code=3)
    finding, = first["finding_ids"]
    original, = cli("show", finding)
    assert original["data"]["finding"]["file"] == "first.py"
    assert original["data"]["finding"]["diagnostic"] == "unmatched ')'"
    decision = cli("review", finding, "confirm", "--reason", "Confirmed pinned diff")
    assert decision["actor"] == service.memory.actor and decision["time"]
    assert decision["data"]["evidence_digest"] == finding[2:]
    proposal = cli("propose", finding)
    protection = proposal["protection_id"]
    assert proposal["artifact"]["scope"]["repository"] == REPO
    assert proposal["original_finding"] == original["data"]
    assert proposal["state"] == "protection"
    cli("decide", protection, "approve", "--reason", "Reviewed guard and scope")
    path = Path(cli("export", protection, "--checkout", str(checkout))["path"])
    document = json.loads(path.read_bytes())
    assert document["approval"]["actor"] == service.memory.actor
    assert document["source_finding_id"] == finding

    # Use a disposable local Git repo to demonstrate the exported manifest is versionable.
    subprocess.run(["git", "-c", "init.templateDir=", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "add", "--", str(path)], check=True)
    tracked = subprocess.check_output(["git", "-C", str(checkout), "ls-files", "--stage"], text=True)
    assert tracked.strip().endswith(f".reivro/protections/{protection}.json")
    path.unlink()
    subprocess.run(["git", "-C", str(checkout), "checkout-index", "--",
                    path.relative_to(checkout).as_posix()], check=True)

    run = cli("run", protection, SECOND, "--checkout", str(checkout), "--github-read", exit_code=3)
    assert run["status"] == "VIOLATION_DETECTED"
    assert run["head_sha"] == f"{102:040x}" and run["version"] == 1
    analysis, = cli("show", run["analysis_id"])
    evidence, = analysis["data"]["report"]["files"]
    assert evidence["file"] == "future.py" and evidence["line"] == 1
    assert evidence["head_file_url"].endswith(f"/blob/{run['head_sha']}/future.py#L1")
    assert cli("run", protection, CLEAN, "--checkout", str(checkout), "--github-read")["status"] == "NO_VIOLATION"
    stats = cli("metrics")
    assert stats["analyses"] == 3 and stats["findings_confirmed"] == 1
    assert stats["protections_proposed"] == stats["protections_approved"] == 1
    assert stats["protections_executed"] == 2 and stats["recurrences_detected"] == 1
    assert stats["analysis_duration_ms"] >= 0 and stats["cost"] is None


def test_explicit_decisions_and_terminal_rejection(scenario):
    service, checkout, calls = scenario
    finding, = service.analyze(FIRST, True)["finding_ids"]
    with pytest.raises(FirewallError, match="Explicitly confirm"):
        service.propose(finding)
    service.decide_finding(finding, "reject", "Reviewer disagreed")
    assert service.metrics()["findings_rejected"] == 1
    assert service.analyze(FIRST, True)["finding_ids"] == [finding]
    with pytest.raises(FirewallError):
        service.decide_finding(finding, "confirm", "Cannot replace history")
    other, = service.analyze(SECOND, True)["finding_ids"]
    service.decide_finding(other, "confirm", "Reviewed")
    proposal = service.propose(other)["protection_id"]
    assert service.propose(other)["protection_id"] == proposal
    with pytest.raises(FirewallError):
        service.export(proposal, checkout)
    service.decide_protection(proposal, "reject", "Scope too broad for project")
    calls.clear()
    assert service.run(proposal, checkout, CLEAN, True)["status"] == "INAPPLICABLE"
    assert not calls
    with pytest.raises(FirewallError):
        service.decide_protection(proposal, "approve", "Cannot bypass rejection")


def test_revocation_persists_and_incomplete_evidence_does_not_trigger(scenario):
    service, checkout, calls = scenario
    _, protection, _ = approved(service, checkout)
    assert service.run(protection, checkout, MISSING, True)["status"] == "INCONCLUSIVE"
    assert service.run(protection, checkout, ERROR, True)["status"] == "ERROR"
    assert service.run(protection, checkout, FIRST, True)["status"] == "INAPPLICABLE"
    event = service.decide_protection(protection, "revoke", "Owner disabled the rule")
    assert event["kind"] == "protection_revoked"
    restarted = firewall.Firewall(Memory(service.memory.directory, REPO))
    calls.clear()
    assert restarted.run(protection, checkout, SECOND, True)["status"] == "INAPPLICABLE"
    assert not calls
    stats = restarted.metrics()
    assert stats["recurrences_detected"] == 0 and stats["inconclusive_runs"] == 1
    assert stats["inconclusive_analyses"] == 1


def test_access_checks_before_network(scenario):
    service, checkout, calls = scenario
    with pytest.raises(FirewallError, match="github-read"):
        service.analyze(FIRST, False)
    other = firewall.Firewall(Memory(service.memory.directory, "other/repo"))
    with pytest.raises(FirewallError, match="another project"):
        other.analyze("https://github.com/other/repo/pull/1", True)
    with pytest.raises(FirewallError, match="this project"):
        service.analyze("https://github.com/other/repo/pull/1", True)
    service.memory.directory.chmod(0o755)
    with pytest.raises(FirewallError, match="private"):
        service.analyze(FIRST, True)
    assert not calls


def test_manifest_version_tamper_and_symlink_fail_closed(scenario, tmp_path):
    service, checkout, calls = scenario
    _, protection, path = approved(service, checkout)
    with pytest.raises(FileExistsError):
        service.export(protection, checkout)
    document = json.loads(path.read_bytes())
    document["version"] = 2
    path.write_text(json.dumps(document))
    calls.clear()
    assert service.run(protection, checkout, SECOND, True)["status"] == "ERROR"
    path.unlink()
    outside = tmp_path / "outside"
    outside.mkdir()
    path.parent.rmdir()
    path.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        service.export(protection, checkout)
    assert service.run(protection, checkout, SECOND, True)["status"] == "ERROR"
    assert not list(outside.iterdir()) and not calls


def test_revocation_during_run_invalidates_result(scenario, monkeypatch):
    service, checkout, _ = scenario
    _, protection, _ = approved(service, checkout)
    verify = firewall.verify_syntax

    def revoke(url, permissions):
        service.decide_protection(protection, "revoke", "Revoked before verification finished")
        return verify(url, permissions)

    monkeypatch.setattr(firewall, "verify_syntax", revoke)
    result = service.run(protection, checkout, SECOND, True)
    assert result["status"] == "INAPPLICABLE" and result["analysis_id"]
    assert service.metrics()["recurrences_detected"] == 0


def test_detects_changed_evidence_and_manifest_in_local_journal(scenario):
    service, checkout, calls = scenario
    finding, protection, _ = approved(service, checkout)
    calls.clear()
    with service.memory.transaction(write=True) as db:
        event = service.memory.history(db, finding)[0]["data"]
        event["finding"]["diagnostic"] = "changed after confirmation"
        db.execute("UPDATE events SET data = ? WHERE subject = ? AND kind = 'finding'",
                   (json.dumps(event), finding))
    with pytest.raises(FirewallError, match="Stored finding does not match its ID"):
        service.run(protection, checkout, SECOND, True)
    with service.memory.transaction(write=True) as db:
        event = service.memory.history(db, protection)[0]["data"]
        event["version"] += 1
        db.execute("UPDATE events SET data = ? WHERE subject = ? AND kind = 'protection'",
                   (json.dumps(event), protection))
    with pytest.raises(FirewallError, match="Stored protection does not match its ID"):
        service.export(protection, checkout)
    assert not calls


def test_revoked_protection_cannot_be_reapproved_by_an_extra_event(scenario):
    service, checkout, calls = scenario
    _, protection, _ = approved(service, checkout)
    service.decide_protection(protection, "revoke", "Retired")
    with service.memory.transaction(write=True) as db:
        service.memory.append(db, "protection_approved", protection,
                              {"artifact_digest": protection[2:]})
    calls.clear()
    with pytest.raises(FirewallError, match="Invalid protection decision history"):
        service.run(protection, checkout, SECOND, True)
    assert not calls


def test_artifact_change_during_verify_cannot_report_violation(scenario, monkeypatch):
    service, checkout, _ = scenario
    _, protection, path = approved(service, checkout)
    verify = firewall.verify_syntax

    def replace(url, permissions):
        path.write_text("{}")
        return verify(url, permissions)

    monkeypatch.setattr(firewall, "verify_syntax", replace)
    result = service.run(protection, checkout, SECOND, True)
    assert result["status"] == "ERROR" and "changed during" in result["reason"]
    assert result["analysis_id"] and service.metrics()["recurrences_detected"] == 0


def test_interrupted_run_records_failure(scenario, monkeypatch):
    service, checkout, _ = scenario
    _, protection, _ = approved(service, checkout)

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(firewall, "verify_syntax", interrupt)
    result = service.run(protection, checkout, SECOND, True)
    assert result["status"] == "ERROR" and "interrupted" in result["reason"]
    assert [e["kind"] for e in service.history(result["run_id"])] == [
        "protection_run_started", "protection_run_finished"]


def test_concurrent_decisions_only_record_one_transition(scenario):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    service, _, _ = scenario
    finding, = service.analyze(FIRST, True)["finding_ids"]
    service.decide_finding(finding, "confirm", "Reviewed")
    protection = service.propose(finding)["protection_id"]
    barrier = Barrier(2)

    def decide(decision):
        barrier.wait(timeout=3)
        try:
            return service.decide_protection(protection, decision, "Reviewed")["kind"]
        except FirewallError:
            return "denied"

    with ThreadPoolExecutor(2) as pool:
        outcomes = set(pool.map(decide, ("approve", "reject")))
    assert "denied" in outcomes
    assert outcomes & {"protection_approved", "protection_rejected"}
    assert len(service.history(protection)) == 2
