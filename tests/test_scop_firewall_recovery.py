"""Real PostgreSQL transitions with synthetic Auth, GitHub and transport events."""
import base64
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from server import scop_firewall_checks as checks
from server import scop_firewall_vercel as hosted
from test_scop_firewall_checks import (OTHER, PROJECT, REVIEWER, SECRET, WORKER, delivery,
                                       metadata, pg, revision, rpc)

SCOPE = {"repository_id": 101, "installation_id": 201}
REPORT = {"status": "INCONCLUSIVE", "rule": checks.RULE, "verifier_version": "verify-v2"}


def request(number):
    ref = revision(number)
    return {**SCOPE, "repository": PROJECT.repository, "base_ref": "main", "delivery": str(uuid4()),
            "pr": ref.pr, "base_sha": ref.base_sha, "head_sha": ref.head_sha}


def ownership(claim):
    return {**SCOPE, **{k: claim[k] for k in ("run_id", "fence", "attempt_id")}}


def expire(pg, claim):
    pg(f"update reivro_cloud.execution_leases set lease_until = clock_timestamp() - interval '1 second' "
       f"where run_id = '{claim['run_id']}';")


def test_claim_concurrent_crash_and_stale_finish(pg):
    req = request(101)
    assert rpc(pg, WORKER, "reserve_durable", req)["state"] == "pending"
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: rpc(pg, WORKER, "claim_durable", req), range(2)))
    first = next(claim for claim in claims if claim["state"] == "running")
    assert sorted(claim["state"] for claim in claims) == ["busy", "running"]
    assert first["fence"] == 1
    old = ownership(first)
    assert "lease lost" in rpc(pg, WORKER, "finish", {**old, "report": REPORT}, valid=False)
    expire(pg, first)
    for action in ("renew_durable", "finish_durable", "fail_durable"):
        assert "lease lost" in rpc(pg, WORKER, action, {**old, "report": REPORT}, valid=False)

    fresh = rpc(pg, WORKER, "claim_durable", {**req, "delivery": str(uuid4())})
    assert fresh["run_id"] == first["run_id"] and fresh["fence"] == 2
    assert fresh["attempt_id"] != first["attempt_id"]
    assert "lease lost" in rpc(pg, WORKER, "finish_durable", {**old, "report": REPORT}, valid=False)
    own = ownership(fresh)
    assert rpc(pg, WORKER, "renew_durable", own)["state"] == "running"
    assert pg(f"select lease_until <= attempt_until from reivro_cloud.execution_leases "
              f"where run_id = '{fresh['run_id']}';") == "t"
    done = rpc(pg, WORKER, "finish_durable", {**own, "report": REPORT})
    assert done == {"state": "completed", "outcome": "INCONCLUSIVE", "run_id": first["run_id"]}
    assert rpc(pg, WORKER, "claim_durable", req) == done
    assert "completed" in rpc(pg, WORKER, "finish_durable", {**own, "report": REPORT}, valid=False)
    assert pg(f"select count(*) from reivro_cloud.events where subject = '{first['run_id']}' "
              "and kind = 'lease_complete';") == "1"


@pytest.mark.parametrize("fail_explicitly", [True, False])
def test_retryable_and_crash_exhaustion(pg, fail_explicitly):
    req = request(102 if fail_explicitly else 103)
    for number in range(1, 4):
        claim = rpc(pg, WORKER, "claim_durable", req)
        assert claim["state"] == "running" and claim["fence"] == number
        if fail_explicitly:
            result = rpc(pg, WORKER, "fail_durable", ownership(claim))
            assert result["state"] == ("terminal" if number == 3 else "retryable")
        else:
            expire(pg, claim)
    result = rpc(pg, WORKER, "claim_durable", req)
    assert result == {"state": "terminal", "outcome": "ERROR", "run_id": claim["run_id"]}
    assert rpc(pg, WORKER, "claim_durable", req) == result


def test_legacy_orphan_adoption_and_cross_tenant(pg):
    req = request(104)
    old = rpc(pg, WORKER, "claim", req)
    assert rpc(pg, WORKER, "claim", req) == {"duplicate": True}
    new = rpc(pg, WORKER, "claim_durable", req)
    assert old["run_id"] == new["run_id"]
    assert "Denied" in rpc(pg, OTHER, "claim_durable", req, valid=False)
    assert "Denied" in rpc(pg, REVIEWER, "claim_durable", req, valid=False)
    assert "Denied" in rpc(pg, WORKER, "claim_durable", req, valid=False, anonymous=True)
    assert "Denied" in rpc(pg, WORKER, "finish_durable",
                           {**ownership(new), "repository_id": 102, "report": REPORT}, valid=False)
    assert "permission denied" in pg("set role authenticated; select * from reivro_cloud.execution_leases;",
                                     valid=False)
    assert "permission denied" in pg(
        "set role authenticated; select reivro_cloud.dispatch_v1('finish', '{}'::jsonb);", valid=False)
    assert rpc(pg, WORKER, "finish_durable", {**ownership(new), "report": REPORT})["state"] == "completed"


def test_consumer_recovers_lost_commit_and_acks_without_reanalysis(pg, monkeypatch):
    body, signature, key, _ = delivery(105)
    item = {"body": base64.b64encode(body).decode(), "signature": signature, "delivery": key}
    failed = set()

    class Memory:
        def __init__(self, ref, key, jwt):
            assert (ref, jwt) == (hosted.STAGING, "fixture-jwt")

        def dispatch(self, action, parameters):
            result = rpc(pg, WORKER, action, parameters)
            if action in {"claim_durable", "finish_durable"} and action not in failed:
                failed.add(action)
                raise checks.CheckError("fixture: response lost after commit")
            return result

    class Evidence:
        def __init__(self, token, project):
            pass

        def pull(self, number):
            return metadata(revision(number))

        def publish(self, payload):
            pytest.fail("DRY RUN attempted to publish")

    ref = revision(105)
    url = f"https://github.com/{PROJECT.repository}"
    regression = {**REPORT, "status": "REGRESSION_DETECTED", "repository": PROJECT.repository,
                  "base_sha": ref.base_sha, "head_sha": ref.head_sha, "pr": ref.pr,
                  "pr_url": f"{url}/pull/{ref.pr}", "compiler": "fixture",
                  "files": [{"status": "REGRESSION_DETECTED", "rule": checks.RULE, "file": "test.py",
                             "line": 1, "diagnostic": "fixture", "exception": "SyntaxError", "excerpt": "+fixture",
                             "base_file_url": f"{url}/blob/{ref.base_sha}/test.py",
                             "head_file_url": f"{url}/blob/{ref.head_sha}/test.py"}]}
    inspections = []

    def inspect(*args):
        inspections.append(True)
        return regression, None

    monkeypatch.setattr(checks, "_inspect", inspect)
    monkeypatch.setenv("REIVRO_PUBLISHABLE_KEY", "fixture")
    monkeypatch.setenv("REIVRO_WORKER_JWT", "fixture-jwt")
    monkeypatch.setenv("REIVRO_GITHUB_INSTALLATION_TOKEN", "fixture")
    options = dict(config=lambda: (PROJECT, SECRET), memory_factory=Memory,
                   github_factory=Evidence, compiler_factory=object)
    with pytest.raises(checks.CheckError, match="response lost"):
        hosted.consume(item, **options)
    with pytest.raises(RuntimeError, match="requires retry"):
        hosted.consume(item, **options)
    assert inspections == []
    run_id = pg(f"select id from reivro_cloud.runs where delivery = '{key}';")
    expire(pg, {"run_id": run_id})
    with pytest.raises(checks.CheckError, match="response lost"):
        hosted.consume(item, **options)
    assert hosted.consume(item, **options) == "COMPLETED"
    assert hosted.consume({**item, "delivery": str(uuid4())}, **options) == "COMPLETED"
    assert len(inspections) == 1
    assert pg(f"select count(*) from reivro_cloud.findings where run_id = '{run_id}';") == "1"
    assert pg(f"select count(*) from reivro_cloud.events where subject = '{run_id}' and kind = 'finish';") == "1"

    finding = pg(f"select id from reivro_cloud.findings where run_id = '{run_id}';")
    review = {"repository_id": 101, "subject": finding, "reason": "fixture review"}
    rpc(pg, REVIEWER, "confirm", review)
    protection = rpc(pg, REVIEWER, "propose", review)
    decision = {**review, "subject": protection["protection_id"], "digest": protection["digest"]}
    rpc(pg, REVIEWER, "approve", decision)
    guarded = rpc(pg, WORKER, "claim_durable", request(106))
    assert guarded["protection_id"] == protection["protection_id"]
    rpc(pg, REVIEWER, "revoke", decision)
    assert rpc(pg, WORKER, "finish_durable", {**ownership(guarded), "report": REPORT})["outcome"] == "INACTIVE"


def test_distinct_worker_takes_expired_claim_and_concurrent_finish_is_single(pg):
    worker_b = "00000000-0000-0000-0000-000000000011"
    project_id = "10000000-0000-0000-0000-000000000001"
    pg(f"insert into auth.users values ('{worker_b}'); "
       f"insert into reivro_cloud.memberships values ('{project_id}', '{worker_b}', 'worker');")
    req = request(107)
    first = rpc(pg, WORKER, "claim_durable", req)
    assert rpc(pg, worker_b, "claim_durable", req)["state"] == "busy"
    expire(pg, first)
    fresh = rpc(pg, worker_b, "claim_durable", req)
    assert first["run_id"] == fresh["run_id"] and fresh["fence"] == 2
    assert "Denied" in rpc(pg, WORKER, "renew_durable", ownership(first), valid=False)
    claimed = {**ownership(fresh), "report": REPORT}

    def finish(_):
        try:
            return rpc(pg, worker_b, "finish_durable", claimed)["state"]
        except AssertionError as error:
            assert "Denied or completed execution" in str(error)
            return "denied"

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(finish, range(2))) == ["completed", "denied"]
