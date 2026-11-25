import io
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from server import scop_agent_integration as agent
from server.scop_firewall_memory import FirewallError
from test_scop_firewall import REPO, scenario


def envelope(pr=1, **changes):
    return {"version": 1, "agent": "codex", "project": REPO, "task_id": str(uuid4()),
            "event_id": str(uuid4()), "pr": pr, "head_sha": f"{pr + 100:040x}", **changes}


def options(service, **changes):
    return SimpleNamespace(**({"repository": REPO, "store": service.memory.directory,
                               "cloud_run": None, "repository_id": None, "protection": None,
                               "checkout": None} | changes))


@pytest.mark.parametrize("changes", [
    {"version": True}, {"version": 2}, {"agent": "unknown"}, {"action": "approve"},
    {"protection": {"approval": True}}, {"evidence": {"status": "PASS"}},
    {"project": "https://not-a-repository"}, {"head_sha": "main"},
])
def test_invalid_contract(changes):
    with pytest.raises((ValueError, FirewallError)):
        agent.validate(envelope(**changes))


def test_operator_cycle_and_adversarial_states(scenario):
    service, checkout, calls = scenario
    first = envelope(agent="independent")
    response = agent.review(first, options(service), {})
    assert response["status"] == "REGRESSION_DETECTED"
    assert response["evidence"]["head_sha"] == first["head_sha"]
    assert len(response["modified_files"]) == 1
    assert "first.py" not in json.dumps(response)
    count = len(calls)
    assert agent.review(first, options(service), {})["reason"] == "duplicate_event"
    assert len(calls) == count
    with pytest.raises(ValueError, match="Conflicting"):
        agent.review({**first, "head_sha": "9" * 40}, options(service), {})
    divergent = agent.review(envelope(head_sha="9" * 40), options(service), {})
    assert divergent["status"] == "INCONCLUSIVE" and not divergent["findings"]
    assert divergent["evidence"] is None

    finding, = response["findings"]
    service.decide_finding(finding, "confirm", "Operator inspected pinned evidence")
    protection = service.propose(finding)["protection_id"]
    service.decide_protection(protection, "approve", "Operator approved the syntax check")
    path = service.export(protection, checkout)["path"]
    guarded = options(service, protection=protection, checkout=checkout)
    result = agent.review(envelope(2, agent="claude-code"), guarded, {})
    assert result["status"] == "VIOLATION_DETECTED"
    assert result["protection"] == {"id": protection, "application": "violation"}

    with open(path, "ab") as artifact:
        artifact.write(b"tampered")
    result = agent.review(envelope(2, agent="cursor"), guarded, {})
    assert result["status"] == "ERROR" and result["evidence"] is None
    service.decide_protection(protection, "revoke", "Operator revoked the guard")
    calls.clear()
    result = agent.review(envelope(2), guarded, {})
    assert result["status"] == "INAPPLICABLE" and not calls


@pytest.mark.parametrize("name", agent.AGENTS)
def test_submission_cli_without_provider(monkeypatch, capsys, name):
    import sys

    request = envelope(agent=name)
    argv = ["agent", "submit"]
    for field in ("agent", "project", "task_id", "event_id", "pr", "head_sha"):
        argv.extend(("--" + field.replace("_", "-"), str(request[field])))
    monkeypatch.setattr(sys, "argv", argv)
    assert agent.main() == 0
    assert json.loads(capsys.readouterr().out) == request


def test_cli_redacts_error_and_rejects_duplicate_fields(monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["agent", "review", "--repository", REPO,
                                    "--store", "/private/sensitive", "--github-read"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(
        b'{"version":1,"version":2,"secret":"DO-NOT-PRINT"}')))
    assert agent.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "ERROR"
    assert "DO-NOT-PRINT" not in output and "/private/sensitive" not in output


def test_cloud_memory_read_only_and_revision_check(scenario, monkeypatch):
    service, _, calls = scenario
    run_id = str(uuid4())
    request = envelope()
    env = {"REIVRO_STAGING_REF": agent.STAGING, "REIVRO_PUBLISHABLE_KEY": "fixture",
           "REIVRO_AGENT_READER_JWT": "private-token-fixture"}
    config = options(service, cloud_run=run_id, repository_id=101)
    head = request["head_sha"]

    class ReadOnlyMemory:
        def __init__(self, ref, key, token):
            assert ref == agent.STAGING and token == env["REIVRO_AGENT_READER_JWT"]

        def read_run(self, repository, run):
            assert (repository, run) == (101, run_id)
            return {"run": {"id": run_id, "outcome": "OBSERVED", "pr": 1, "head_sha": head,
                            "base_sha": "a" * 40, "report": {"repository": REPO, "head_sha": head,
                            "base_sha": "a" * 40, "files": [], "diagnostic": env["REIVRO_AGENT_READER_JWT"]}},
                    "findings": [{"id": run_id, "evidence": {"secret": env["REIVRO_AGENT_READER_JWT"]}}]}

    monkeypatch.setattr(agent, "StagingMemory", ReadOnlyMemory)
    result = agent.review(request, config, env)
    assert result["status"] == "OBSERVED" and result["findings"] == [run_id]
    assert env["REIVRO_AGENT_READER_JWT"] not in json.dumps(result)
    head = "b" * 40
    assert agent.review(envelope(), config, env)["status"] == "INCONCLUSIVE"
    assert agent.review(envelope(), config, {})["status"] == "ERROR"
    assert not calls


def test_review_cli_reports_pinned_regression(scenario, monkeypatch, capsys):
    import sys

    service, _, _ = scenario
    request = envelope()
    monkeypatch.setattr(sys, "argv", ["agent", "review", "--repository", REPO,
                                    "--store", str(service.memory.directory), "--github-read"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())))
    assert agent.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["verifier_status"] == "REGRESSION_DETECTED"
    assert result["evidence"]["source"] == "verified_public_pr"


def test_feedback_requires_exact_journal_report_and_operator_grant(scenario, monkeypatch):
    from server.scop_agent_feedback import checked_feedback
    from server.scop_verify_syntax import github
    from test_scop_firewall import approved

    service, checkout, _ = scenario
    _, protection, _ = approved(service, checkout)
    config = options(service, protection=protection, checkout=checkout)
    violation = envelope(2)
    report = agent.review(violation, config, {})
    event = report["event_id"]
    assert report["status"] == "VIOLATION_DETECTED"
    assert report["feedback"]["decision"] == "wait_for_operator"
    assert checked_feedback(service.memory, report, event) == report
    for altered in ({**report, "requested_head_sha": "9" * 40},
                    {**report, "status": "PASS"},
                    {**report, "feedback": {"decision": "correction_authorized"}}):
        with pytest.raises(ValueError, match="journal"):
            checked_feedback(service.memory, altered, event, authorize=True)

    correction = envelope(2, task_id=violation["task_id"], head_sha=f"{103:040x}")
    followup = options(service, protection=protection, checkout=checkout, after_correction=event)
    with pytest.raises(ValueError, match="authorization"):
        agent.review(correction, followup, {})
    grant = checked_feedback(service.memory, report, event, authorize=True)
    assert grant["feedback"] == {"version": 1, "decision": "correction_authorized",
                                  "attempt": 1, "limit": 2}
    with pytest.raises(ValueError, match="authorization"):
        agent.review({**correction, "head_sha": violation["head_sha"]}, followup, {})

    fetch = github.fetch_json

    def corrected(url, deadline):
        result = fetch(url.replace("/pulls/2", "/pulls/3"), deadline)
        if url.endswith("/pulls/2"):
            return {**result, "html_url": "https://github.com/example/fixture/pull/2"}
        return result

    with monkeypatch.context() as patch:
        patch.setattr(github, "fetch_json", corrected)
        assert agent.review(correction, followup, {})["status"] == "NO_VIOLATION"
    with pytest.raises(ValueError, match="authorization"):
        agent.review({**correction, "event_id": str(uuid4())}, followup, {})

    def another_violation():
        return agent.review(envelope(2, task_id=violation["task_id"]), config, {})

    second = another_violation()
    assert checked_feedback(service.memory, second, second["event_id"], authorize=True)["feedback"]["attempt"] == 2
    third = another_violation()
    with pytest.raises(ValueError, match="budget"):
        checked_feedback(service.memory, third, third["event_id"], authorize=True)
    service.decide_protection(protection, "revoke", "Operator revoked")
    with pytest.raises(ValueError, match="no longer active"):
        checked_feedback(service.memory, third, third["event_id"], authorize=True)


def test_process_exit_after_reservation_recovers_without_duplicate_effects(scenario, monkeypatch):
    import subprocess
    import sys

    service, _, calls = scenario
    item = envelope()
    payload = json.dumps(item)
    script = """
import json, os, sys
from types import SimpleNamespace
from server import scop_agent_integration as agent
def interrupted(*args, **kwargs):
    os._exit(17)
agent.local_result = interrupted
args = SimpleNamespace(repository="example/fixture", store=sys.argv[1], cloud_run=None,
                       repository_id=None, protection=None, checkout=None)
agent.review(json.loads(sys.argv[2]), args, {})
"""
    result = subprocess.run([sys.executable, "-c", script, str(service.memory.directory), payload],
                            timeout=10, capture_output=True)
    assert result.returncode == 17 and not result.stdout
    subject = "agent-event-" + item["event_id"]
    assert [entry["kind"] for entry in service.history(subject)] == ["agent_submission"]
    assert not calls

    original = agent.local_result

    def committed_but_no_response(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(agent, "local_result", committed_but_no_response)
        with pytest.raises(KeyboardInterrupt):
            agent.review(item, options(service), {})
    assert [entry["kind"] for entry in service.history(subject)] == ["agent_submission", "agent_result"]
    assert service.metrics()["analyses"] == 1
    from server.scop_agent_feedback import checked_feedback
    assert checked_feedback(service.memory, None, item["event_id"])["status"] == "REGRESSION_DETECTED"
    count = len(calls)
    assert agent.review(item, options(service), {})["reason"] == "duplicate_event"
    assert len(calls) == count
