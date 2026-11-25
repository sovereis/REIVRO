import runpy
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "ops/vercel-pilot/staging/check_worker.py"


def test_worker_probe_pins_staging_and_proves_subject(monkeypatch):
    from server import scop_firewall_checks as checks

    owner = str(uuid4())
    calls = []

    def request(method, url, headers, payload=None, **kwargs):
        calls.append((method, url))
        assert headers["apikey"] == "sb_publishable_fixture"
        assert headers["Authorization"] == "Bearer fixture.user.jwt"
        if method == "GET":
            return {"id": owner, "role": "authenticated", "is_anonymous": False}
        assert payload["p_repository_id"] == 1469495108
        return None

    monkeypatch.setattr(checks, "_request", request)
    probe = runpy.run_path(str(HARNESS))["check_worker"]
    env = {
        "REIVRO_STAGING_REF": "lbklqqqbmeyseeccdqog",
        "REIVRO_PUBLISHABLE_KEY": "sb_publishable_fixture",
        "REIVRO_WORKER_JWT": "fixture.user.jwt",
        "REIVRO_WORKER_USER_ID": owner,
    }
    probe(env)
    assert calls == [
        ("GET", "https://lbklqqqbmeyseeccdqog.supabase.co/auth/v1/user"),
        ("POST", "https://lbklqqqbmeyseeccdqog.supabase.co/rest/v1/rpc/read_run"),
    ]
    calls.clear()
    with pytest.raises(ValueError, match="staging"):
        probe({**env, "REIVRO_STAGING_REF": "hnlmnswotenppgdqxvkv"})
    assert not calls
    with pytest.raises(ValueError, match="identity mismatch"):
        probe({**env, "REIVRO_WORKER_USER_ID": str(uuid4())})
    assert len(calls) == 1


def test_worker_trigger_declaration_with_installed_sdk():
    queue = pytest.importorskip("vercel.queue")
    runpy.run_path(str(ROOT / "ops/vercel-pilot/worker.py"))
    subscription, = queue.get_subscriptions()
    assert subscription.max_attempts == 6
    assert subscription.retry_after_seconds == 150
    assert subscription.max_concurrency == 1
    # Even three full application leases and all six delayed deliveries fit.
    assert 120 < subscription.retry_after_seconds
    assert 6 * (120 + subscription.retry_after_seconds) < 3600


def test_read_only_membership_matrix_and_revoked_reviewer(monkeypatch):
    from server import scop_firewall_checks as checks

    monkeypatch.syspath_prepend(str(HARNESS.parent))
    matrix = runpy.run_path(str(HARNESS.with_name("check_memberships.py")))
    identities = {f"fixture.{i}.jwt": str(uuid4()) for i in range(5)}
    env = {
        "REIVRO_STAGING_REF": "lbklqqqbmeyseeccdqog",
        "REIVRO_PUBLISHABLE_KEY": "sb_publishable_fixture",
        "REIVRO_WORKER_USER_ID": identities["fixture.2.jwt"],
        "REIVRO_FIXTURE_A_REPOSITORY_ID": "101",
        "REIVRO_FIXTURE_B_REPOSITORY_ID": "102",
        "REIVRO_FIXTURE_A_RUN_ID": str(uuid4()),
        "REIVRO_FIXTURE_B_RUN_ID": str(uuid4()),
    }
    for i, (variable, _) in enumerate(matrix["MATRIX"]):
        env[variable] = f"fixture.{i}.jwt"
    revoked = False
    rpc_calls = []

    def request(method, url, headers, payload=None, **kwargs):
        token = headers["Authorization"].removeprefix("Bearer ")
        if method == "GET":
            assert url.endswith("/auth/v1/user")
            return {"id": identities[token], "role": "authenticated", "is_anonymous": False}
        assert url.endswith("/rpc/read_run")
        rpc_calls.append(payload)
        column = payload["p_repository_id"]
        if ((column == 101 and token in {"fixture.0.jwt", "fixture.1.jwt"}
                and not (revoked and token == "fixture.0.jwt"))
                or (column == 102 and token == "fixture.3.jwt")):
            return {"run": {"id": payload["p_run_id"]}}
        return None

    monkeypatch.setattr(checks, "_request", request)
    probe = matrix["check_memberships"]
    probe(env)
    assert len(rpc_calls) == 10
    revoked = True
    probe(env, reviewer_revoked=True)
    with pytest.raises(ValueError, match="Expected fixture run"):
        probe(env)
    with pytest.raises(ValueError, match="distinct"):
        probe({**env, "REIVRO_NO_MEMBERSHIP_JWT": env["REIVRO_WORKER_JWT"]}, reviewer_revoked=True)
