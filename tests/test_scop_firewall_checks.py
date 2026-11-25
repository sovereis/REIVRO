"""Webhook authentication, GitHub transport contracts and staged end-to-end smoke."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha1, sha256
import hmac
import json
import os
import subprocess
from uuid import uuid4

import pytest

from server import scop_firewall_checks as checks
from server import scop_firewall_pilot as pilot
from server import scop_github_evidence as evidence
from server import scop_verify_syntax as syntax


PROJECT = checks.Project("example/fixture", 101, 201, "main")
SECRET = b"local-test-signing-key-do-not-use"
WORKER = "00000000-0000-0000-0000-000000000001"
REVIEWER = "00000000-0000-0000-0000-000000000002"
OTHER = "00000000-0000-0000-0000-000000000003"


def revision(number):
    return checks.Revision(number, f"{number:040x}", f"{number + 100:040x}")


def metadata(rev):
    return {
        "state": "open", "number": rev.pr,
        "base": {"sha": rev.base_sha, "ref": "main",
                 "repo": {"id": 101, "full_name": "example/fixture", "private": False}},
        "head": {"sha": rev.head_sha},
    }


def delivery(number, alter=lambda payload: None):
    rev = revision(number)
    payload = {"action": "opened", "installation": {"id": 201},
               "repository": metadata(rev)["base"]["repo"], "number": number,
               "pull_request": metadata(rev)}
    alter(payload)
    body = json.dumps(payload).encode()
    return body, "sha256=" + hmac.digest(SECRET, body, "sha256").hex(), str(uuid4()), "pull_request"


@pytest.mark.parametrize("variant", ["signature", "body", "install", "repo", "base", "event", "delivery"])
def test_unauthenticated_or_mismatched_deliveries_are_rejected(variant):
    def alter(payload):
        if variant == "install":
            payload["installation"]["id"] = 999
        elif variant == "repo":
            payload["repository"]["id"] = 999
        elif variant == "base":
            payload["pull_request"]["base"]["ref"] = "untrusted"

    args = list(delivery(1, alter))
    if variant == "signature":
        args[1] = "sha256=" + "0" * 64
    elif variant == "body":
        args[0] += b" "
    elif variant == "event":
        args[3] = "push"
    elif variant == "delivery":
        args[2] = "not-a-uuid"
    with pytest.raises(checks.CheckError):
        checks.handle(*args, project=PROJECT, secret=SECRET, memory=None, github=None)


def test_stale_event_never_claims_or_publishes():
    class GitHub:
        def pull(self, number):
            return metadata(revision(2))

    assert checks.handle(*delivery(1), project=PROJECT, secret=SECRET,
                         memory=None, github=GitHub()) == {"status": "STALE"}


def test_staging_client_blocks_production_and_passes_user_jwt(monkeypatch):
    with pytest.raises(checks.CheckError, match="production"):
        checks.StagingMemory("hnlmnswotenppgdqxvkv", "sb_publishable_fixture", "jwt")
    calls = []
    monkeypatch.setattr(checks, "_request", lambda *args: calls.append(args) or {"ok": True})
    client = checks.StagingMemory("a" * 20, "sb_publishable_fixture", "fixture-jwt")
    assert client.dispatch("confirm", {"subject": "fixture"}) == {"ok": True}
    method, url, headers, payload = calls[0]
    assert method == "POST" and url.endswith(".supabase.co/rest/v1/rpc/dispatch")
    assert headers["Authorization"] == "Bearer fixture-jwt"
    assert headers["Content-Profile"] == "reivro_checks_api"
    assert payload["action"] == "confirm"


def contents(path, raw):
    return {"type": "file", "path": path, "encoding": "base64", "size": len(raw),
            "content": base64.b64encode(raw).decode(),
            "sha": sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()}


def test_artifact_transport_uses_pinned_ref_and_rejects_tampering(monkeypatch):
    base = revision(1).base_sha
    observed = []
    value = contents(checks.ARTIFACT, b"manifest")
    def request(method, url, headers, **options):
        observed.append((method, url))
        return value
    monkeypatch.setattr(checks, "_request", request)
    api = checks.GitHub("installation-fixture", PROJECT)
    assert api.artifact(base) == b"manifest"
    assert observed == [("GET", f"https://api.github.com/repos/example/fixture/contents/{checks.ARTIFACT}?ref={base}")]
    value["content"] = base64.b64encode(b"tampered").decode()
    with pytest.raises(checks.CheckError, match="integrity"):
        api.artifact(base)


@pytest.fixture
def pg():
    name = os.getenv("REIVRO_LOCAL_TEST_POSTGRES", "")
    if not name.startswith("reivro-staging-test-"):
        pytest.skip("run scripts/test-firewall-staging.sh for the isolated PostgreSQL flow")

    def run(sql, *, valid=True):
        result = subprocess.run(
            ["docker", "exec", "-i", name, "psql", "-XqAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres"],
            input=sql, capture_output=True, text=True, timeout=10,
        )
        if valid:
            assert result.returncode == 0, result.stderr
            return result.stdout.strip()
        assert result.returncode != 0, result.stdout
        return result.stderr

    return run


def rpc(pg, actor, action, parameters, *, valid=True, role="authenticated", anonymous=False):
    # The fixture stands in for PostgREST after JWT validation. It supplies only
    # fixed test identities; neither SQL nor real user claims come from a webhook.
    payload = json.dumps(parameters, ensure_ascii=True).replace("'", "''")
    uid = actor or ""
    raw = pg(f"begin; set local role {role}; set local request.jwt.claim.sub = '{uid}'; "
             f"set local request.jwt.claims = '{json.dumps({'is_anonymous': anonymous})}'; "
             f"select reivro_checks_api.dispatch('{action}', '{payload}'::jsonb); commit;", valid=valid)
    return json.loads(raw) if valid else raw


def test_finish_report_matches_hosted_pr_contract(pg, monkeypatch):
    rev = revision(90)
    scope = {"repository_id": 101, "installation_id": 201}

    def dispatch(method, url, headers, payload):
        assert method == "POST"
        assert url == "https://lbklqqqbmeyseeccdqog.supabase.co/rest/v1/rpc/dispatch"
        assert headers["Content-Profile"] == "reivro_checks_api"
        return rpc(pg, WORKER, payload["action"], payload["request"])

    monkeypatch.setattr(checks, "_request", dispatch)
    client = checks.StagingMemory("lbklqqqbmeyseeccdqog", "sb_publishable_fixture", "fixture-jwt")
    claim_request = {
        **scope, "repository": PROJECT.repository, "base_ref": "main", "delivery": str(uuid4()),
        "pr": rev.pr, "base_sha": rev.base_sha, "head_sha": rev.head_sha,
    }
    assert "Denied" in rpc(pg, WORKER, "claim", claim_request, valid=False, anonymous=True)
    claim = client.dispatch("claim", claim_request)
    report = {"status": "PASS", "rule": "python-syntax-regression", "verifier_version": "verify-v2",
              "repository": PROJECT.repository, "pr": rev.pr, "base_sha": rev.base_sha,
              "head_sha": rev.head_sha, "compiler": "fixture",
              "files": [{"status": "PASS", "file": "fixture.py"}]}
    request = {**scope, "run_id": claim["run_id"], "report": report}
    assert "Report identity does not match claim" in rpc(pg, WORKER, "finish", request, valid=False)

    report["pr_url"] = "https://github.com/example/fixture/pull/91"
    assert "Report identity does not match claim" in rpc(pg, WORKER, "finish", request, valid=False)

    # GitHub's canonical repository casing may differ from the database key.
    report["pr_url"] = "https://github.com/Example/Fixture/pull/90"
    assert client.dispatch("finish", request) == {"run_id": claim["run_id"], "outcome": "OBSERVED"}


@pytest.mark.parametrize("dry_run", [False, True])
def test_isolated_cloud_and_checks_lifecycle(pg, monkeypatch, tmp_path, dry_run):
    offset = 200 if dry_run else 0

    def rev(number):
        return revision(number + offset)

    def signed(number):
        return delivery(number + offset)
    # Auth subjects and GitHub responses are fixtures. PostgreSQL, RLS and the
    # VERIFY subprocess are real. No token, webhook or Check is sent to GitHub.
    scope = {"repository_id": 101, "installation_id": 201}
    trust = {}

    def read_count(uid):
        return int(pg(f"begin; set local role authenticated; set local request.jwt.claim.sub = '{uid}'; "
                      "select count(*) from reivro_cloud.runs; commit;"))

    initial_reviewer_runs = read_count(REVIEWER)

    class Memory:
        def dispatch(self, action, request):
            return rpc(pg, WORKER, action, request)

    def verify_fetch(url, deadline):
        for number in range(1, 8):
            ref = rev(number)
            pr = ref.pr
            endpoint = f"https://api.github.com/repos/example/fixture/pulls/{pr}"
            path = "first.py" if number == 1 else "later.py"
            old = contents(path, b"x = 1\n")
            line = b"x = 2" if number == 3 else b"x = )"
            new = contents(path, line + b"\n")
            if url == endpoint:
                return {**metadata(ref), "changed_files": 1,
                        "html_url": f"https://github.com/example/fixture/pull/{pr}"}
            if url == endpoint + "/files?per_page=100&page=1":
                return [{"filename": path, "status": "modified", "additions": 1, "deletions": 1,
                         "sha": new["sha"], "patch": "@@ -1 +1 @@\n-x = 1\n+" + line.decode()}]
            prefix = "https://api.github.com/repos/example/fixture/contents/"
            if url == f"{prefix}{path}?ref={ref.base_sha}":
                return old
            if url == f"{prefix}{path}?ref={ref.head_sha}":
                return new
        raise AssertionError("unexpected evidence endpoint")

    monkeypatch.setattr(evidence, "fetch_json", verify_fetch)

    published = []
    def transport(method, url, headers, payload=None, limit=None):
        if url == "https://lbklqqqbmeyseeccdqog.supabase.co/rest/v1/rpc/dispatch":
            assert method == "POST" and headers["Content-Profile"] == "reivro_checks_api"
            assert headers["Authorization"] == "Bearer fixture-worker"
            return rpc(pg, WORKER, payload["action"], payload["request"])
        assert headers["Authorization"] == "Bearer fixture-installation"
        if url.endswith("/check-runs"):
            assert method == "POST"
            published.append(payload)
            return {"id": len(published), **payload}
        if "/contents/" in url:
            pin = url.rsplit("ref=", 1)[1]
            return contents(checks.ARTIFACT, trust[pin])
        return metadata(revision(int(url.rsplit("/", 1)[1])))

    monkeypatch.setattr(checks, "_request", transport)

    def send(number, replay=None):
        args = replay or signed(number)
        if dry_run:
            return checks.analyze(*args, project=PROJECT, secret=SECRET, memory=memory,
                                  github=checks.GitHubEvidence("fixture-installation", PROJECT),
                                  executor=execute, durable=True)
        return checks.handle(*args, project=PROJECT, secret=SECRET,
                             memory=Memory(), github=checks.GitHub("fixture-installation", PROJECT))

    queue = pilot.Queue(tmp_path / "deliveries.sqlite")
    body, signature, key, event = signed(1)
    pilot.accept_delivery(queue, PROJECT, SECRET, body, signature, key, event)
    memory = checks.StagingMemory("lbklqqqbmeyseeccdqog", "sb_publishable_fixture", "fixture-worker")
    compiled = []

    def execute(source, deadline):
        compiled.append(source)
        return syntax._compile(source, deadline)

    if dry_run:
        original = send(1, (body, signature, key, event))
        assert original["status"] == "OBSERVED"
    else:
        assert pilot.process(queue, PROJECT, SECRET, memory,
                             checks.GitHubEvidence("fixture-installation", PROJECT), executor=execute)
        with closing(queue.connect()) as db:
            saved = json.loads(db.execute("SELECT result FROM deliveries WHERE id=?", (key,)).fetchone()[0])
        assert not published
        original = checks.publish_result(saved, checks.GitHub("fixture-installation", PROJECT))
        assert original["status"] == "OBSERVED" and published[-1]["conclusion"] == "neutral"
    assert compiled == [b"x = 1\n", b"x = )\n"]

    def read_run(actor):
        return pg(f"begin; set local role authenticated; set local request.jwt.claim.sub = '{actor}'; "
                  f"select reivro_checks_api.read_run(101, '{original['run_id']}'); commit;")
    assert read_run(OTHER) == read_run(WORKER) == ""
    inspected = json.loads(read_run(REVIEWER))
    assert inspected["run"]["head_sha"] == rev(1).head_sha
    finding = inspected["findings"][0]["id"]
    request = {**scope, "subject": finding, "reason": "Reviewed the pinned evidence"}
    for actor in (None, OTHER, WORKER):
        assert "Denied" in rpc(pg, actor, "confirm", request, valid=False)
    assert "permission denied" in rpc(pg, None, "confirm", request, valid=False, role="anon")
    assert "Confirmed finding required" in rpc(pg, REVIEWER, "propose", request, valid=False)
    assert rpc(pg, REVIEWER, "confirm", request)["action"] == "confirm"
    proposal = rpc(pg, REVIEWER, "propose", request)
    approval = {**request, "subject": proposal["protection_id"], "digest": proposal["digest"]}
    assert "Denied" in rpc(pg, REVIEWER, "approve", {**approval, "digest": "wrong"}, valid=False)
    assert sha256(proposal["manifest"].encode()).hexdigest() == proposal["digest"]

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(rpc, pg, REVIEWER, "approve", approval) for _ in range(2)]
        results = []
        for future in futures:
            try:
                results.append(future.result()["action"])
            except AssertionError as exc:
                assert "Denied protection decision" in str(exc)
                results.append("denied")
    assert sorted(results) == ["approve", "denied"]

    # Build and recover the artifact from a disposable Git index.
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory() as directory:
        path = Path(directory) / checks.ARTIFACT
        path.parent.mkdir(parents=True)
        path.write_bytes(proposal["manifest"].encode())
        subprocess.run(["git", "-c", "init.templateDir=", "init", "-q", directory], check=True)
        subprocess.run(["git", "-C", directory, "add", "--", checks.ARTIFACT], check=True)
        approved = subprocess.check_output(["git", "-C", directory, "show", ":" + checks.ARTIFACT])
    trust.update({rev(number).base_sha: approved for number in (2, 3, 4, 5, 6)})
    second = signed(2)
    result = send(2, second)
    assert result["status"] == "VIOLATION"
    assert result["head_sha"] == rev(2).head_sha
    if not dry_run:
        assert published[-1]["conclusion"] == "failure"
        assert published[-1]["head_sha"] == rev(2).head_sha
        assert published[-1]["external_id"] == result["run_id"]
    before = len(published)
    repeated = "COMPLETED" if dry_run else "DUPLICATE"
    assert send(2, second)["status"] == send(2)["status"] == repeated
    assert len(published) == before
    assert send(3)["status"] == "PASS"
    trust[rev(4).base_sha] += b" "
    assert send(4)["status"] == "INCONCLUSIVE"
    if not dry_run:
        assert published[-1]["conclusion"] == "neutral"

    # Revoke between claim and finish. The worker cannot finalize a violation.
    real_finish = Memory.dispatch
    def revoke_on_finish(self, action, request):
        if action in {"finish", "finish_durable"}:
            assert rpc(pg, REVIEWER, "revoke", approval)["action"] == "revoke"
        return real_finish(self, action, request)
    with monkeypatch.context() as patch:
        if dry_run:
            def transport_with_revocation(method, url, headers, payload=None, limit=None):
                if payload and payload.get("action") == "finish_durable":
                    assert rpc(pg, REVIEWER, "revoke", approval)["action"] == "revoke"
                return transport(method, url, headers, payload, limit)

            patch.setattr(checks, "_request", transport_with_revocation)
        else:
            patch.setattr(Memory, "dispatch", revoke_on_finish)
        assert send(5)["status"] == "INACTIVE"
    assert send(6)["status"] == "OBSERVED"
    if dry_run:
        assert not published
    assert "Denied" in rpc(pg, REVIEWER, "approve", approval, valid=False)

    # A role claim alone is not authority. Users see records only in their project.
    assert read_count(REVIEWER) == initial_reviewer_runs + 6
    assert read_count(OTHER) == read_count(WORKER) == 0
    assert pg(f"begin; set local role authenticated; set local request.jwt.claim.sub = '{OTHER}'; "
              "select repository from reivro_cloud.projects; commit;") == "example/other"
    assert "permission denied" in pg("set role service_role; select * from reivro_cloud.runs;", valid=False)
    denied_write = pg(f"begin; set local role authenticated; set local request.jwt.claim.sub = '{REVIEWER}'; "
                      "update reivro_cloud.protections set state = 'approved'; commit;", valid=False)
    assert "permission denied" in denied_write
    assert "Denied" in rpc(pg, WORKER, "claim", {
        **scope, "repository_id": 102, "repository": "example/other", "base_ref": "main",
        "delivery": str(uuid4()), "pr": 1, "base_sha": revision(1).base_sha, "head_sha": rev(1).head_sha,
    }, valid=False)


    def claim_once(delivery_id):
        return rpc(pg, WORKER, "claim", {
            **scope, "repository": "example/fixture", "base_ref": "main", "delivery": delivery_id,
            "pr": rev(7).pr, "base_sha": rev(7).base_sha, "head_sha": rev(7).head_sha,
        })

    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(claim_once, (str(uuid4()), str(uuid4()))))
    assert sum(c.get("duplicate") is True for c in claims) == 1
    assert sum("run_id" in c for c in claims) == 1
    if dry_run:
        project_id = "10000000-0000-0000-0000-000000000001"
        pg(f"delete from reivro_cloud.memberships where project_id = '{project_id}' "
           f"and user_id = '{REVIEWER}';")
        try:
            assert read_run(REVIEWER) == ""
            assert "Denied" in rpc(pg, REVIEWER, "confirm", request, valid=False)
        finally:
            pg(f"insert into reivro_cloud.memberships values ('{project_id}', '{REVIEWER}', 'reviewer');")



@pytest.mark.parametrize(("provider_status", "status", "conclusion"), [
    (404, "INCONCLUSIVE", "neutral"),
    (403, "ERROR", "action_required"),
    (429, "ERROR", "action_required"),
    (503, "ERROR", "action_required"),
])
def test_artifact_provider_error_is_not_a_success(monkeypatch, provider_status, status, conclusion):
    def request(method, url, headers, payload=None, **kwargs):
        if "/contents/" in url:
            raise checks.ProviderHTTPError(provider_status)
        if url.endswith("/check-runs"):
            assert payload["conclusion"] == conclusion
            return {"id": 1, **payload}
        return metadata(revision(1))

    class Memory:
        def dispatch(self, action, request):
            if action == "claim":
                return {"run_id": WORKER, "protection_id": OTHER, "artifact_digest": "a" * 64}
            assert request["report"]["status"] == status
            return {"run_id": WORKER, "outcome": status}

    monkeypatch.setattr(checks, "_request", request)
    result = checks.handle(*delivery(1), project=PROJECT, secret=SECRET,
                           memory=Memory(), github=checks.GitHub("fixture-installation", PROJECT))
    assert result["status"] == status


@pytest.mark.parametrize("mismatch", ["lost", "head_sha", "external_id", "conclusion", "status"])
def test_publish_ack_must_match_and_never_retries_post(monkeypatch, mismatch):
    body = delivery(1)
    posts = []
    class GitHub:
        def pull(self, number):
            return metadata(revision(1))

        def publish(self, check):
            posts.append(check)
            if mismatch == "lost":
                raise checks.CheckError("Provider response unavailable")
            return {"id": 1, **check, mismatch: "other"}

    class Memory:
        claimed = False

        def dispatch(self, action, request):
            if action == "claim":
                if self.claimed:
                    return {"duplicate": True}
                self.claimed = True
                return {"run_id": WORKER}
            assert request["run_id"] == WORKER
            return {"run_id": WORKER, "outcome": "OBSERVED"}

    monkeypatch.setattr(checks, "verify_syntax", lambda *args: {"status": "ERROR"})
    memory, github = Memory(), GitHub()
    args = {"project": PROJECT, "secret": SECRET, "memory": memory, "github": github}
    assert checks.handle(*body, **args)["status"] == "PUBLICATION_UNCERTAIN"
    assert checks.handle(*body, **args)["status"] == "DUPLICATE"
    assert len(posts) == 1


def test_inconsistent_database_success_is_not_published(monkeypatch):
    class GitHub:
        def pull(self, number):
            return metadata(revision(1))

        def publish(self, check):
            pytest.fail("An unverified success reached GitHub")

    class Memory:
        def dispatch(self, action, request):
            if action == "claim":
                return {"run_id": WORKER}
            return {"run_id": WORKER, "outcome": "PASS"}

    monkeypatch.setattr(checks, "verify_syntax", lambda *args: {"status": "ERROR"})
    with pytest.raises(checks.CheckError, match="does not match verified evidence"):
        checks.handle(*delivery(1), project=PROJECT, secret=SECRET, memory=Memory(), github=GitHub())
