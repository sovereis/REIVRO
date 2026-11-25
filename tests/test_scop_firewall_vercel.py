import asyncio
import base64
from contextlib import contextmanager
from types import SimpleNamespace
from time import monotonic
from uuid import uuid4

import pytest

from server import scop_firewall_checks as checks
from server import scop_firewall_sandbox as sandbox
from server import scop_firewall_vercel as hosted
from test_scop_firewall_checks import PROJECT, SECRET, delivery, metadata, revision


def invoke(app, chunks, headers=(), *, path=hosted.WEBHOOK):
    messages = iter({"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
                    for i, chunk in enumerate(chunks))
    response = []

    async def receive():
        return next(messages)

    async def send(message):
        response.append(message)

    asyncio.run(app({"type": "http", "path": path, "method": "POST",
                     "headers": headers}, receive, send))
    assert response[-1]["body"] == b""
    return response[0]["status"]


def webhook_headers(signature, key, event):
    return [(b"x-hub-signature-256", signature.encode()), (b"x-github-delivery", key.encode()),
            (b"x-github-event", event.encode())]


def test_asgi_waits_for_queue_and_preserves_signed_bytes(caplog):
    body, signature, key, event = delivery(1)
    headers = webhook_headers(signature, key, event)
    accepted = []

    async def enqueue(*item):
        await asyncio.sleep(0)
        accepted.append(item)

    app = hosted.make_app(config=lambda: (PROJECT, SECRET), enqueue=enqueue)
    assert invoke(app, [body[:12], body[12:]], headers) == 202
    assert accepted == [(key, body, signature)]

    async def unavailable(*item):
        raise RuntimeError("sensitive upstream details")

    app = hosted.make_app(config=lambda: (PROJECT, SECRET), enqueue=unavailable)
    assert invoke(app, [body], headers) == 503
    assert "sensitive upstream details" not in caplog.text


@pytest.mark.parametrize("change", [
    lambda item: item["installation"].update(id=999),
    lambda item: item["repository"].update(id=999),
    lambda item: item["pull_request"]["head"].update(sha="bad"),
])
def test_signed_out_of_scope_messages_never_reach_queue(change):
    body, signature, key, event = delivery(1, change)

    async def enqueue(*item):
        pytest.fail("Unexpected enqueue")

    app = hosted.make_app(config=lambda: (PROJECT, SECRET), enqueue=enqueue)
    assert invoke(app, [body], webhook_headers(signature, key, event)) == 403


def test_hmac_precedes_json_and_stream_limit(monkeypatch):
    body, signature, key, event = delivery(1)

    def decode(*args):
        pytest.fail("Unverified payload parsed")

    monkeypatch.setattr(checks, "_decode_object", decode)
    app = hosted.make_app(config=lambda: (PROJECT, SECRET))
    headers = webhook_headers(signature, key, event)
    assert invoke(app, [body + b"x"], headers) == 403
    assert invoke(app, [body], headers + [headers[0]]) == 400
    assert invoke(app, [b"x" * checks.MAX_WEBHOOK, b"x"], headers) == 413


def test_real_sdk_producer_contract_at_network_boundary(monkeypatch):
    queue = pytest.importorskip("vercel.queue")
    body, signature, key, _ = delivery(1)
    sent = []

    async def send(topic, item, *, idempotency_key):
        sent.append((topic, item, idempotency_key))
        if len(sent) == 2:
            raise queue.DuplicateIdempotencyKeyError("duplicate")
        return "accepted" if len(sent) == 1 else None

    monkeypatch.setattr(queue, "send", send)
    asyncio.run(hosted.publish(key, body, signature))
    asyncio.run(hosted.publish(key, body, signature))
    assert sent[0] == sent[1]
    assert base64.b64decode(sent[0][1]["body"]) == body
    assert sent[0][2] == key
    with pytest.raises(RuntimeError, match="acceptance"):
        asyncio.run(hosted.publish(key, body, signature))


def test_dry_run_retry_and_revision_dedup_with_injected_transports(monkeypatch, caplog):
    monkeypatch.setenv("REIVRO_PUBLISHABLE_KEY", "test-key")
    monkeypatch.setenv("REIVRO_WORKER_JWT", "test-jwt")
    monkeypatch.setenv("REIVRO_GITHUB_INSTALLATION_TOKEN", "test-read-token")
    run = str(uuid4())
    seen = set()
    transitions = []

    class Memory:
        def __init__(self, ref, key, jwt):
            assert (ref, key, jwt) == (hosted.STAGING, "test-key", "test-jwt")

        def dispatch(self, action, request):
            if action == "claim_durable":
                if not transitions:
                    transitions.append("transport-failure")
                    raise checks.CheckError("fixture unavailable")
                revision_key = (request["pr"], request["base_sha"], request["head_sha"])
                if revision_key in seen:
                    return {"state": "completed", "run_id": run}
                seen.add(revision_key)
                transitions.append("claim")
                return {"state": "running", "run_id": run, "attempt_id": str(uuid4()), "fence": 1}
            if action == "renew_durable":
                return {"state": "running", "run_id": run}
            assert action == "finish_durable"
            transitions.append("finish")
            return {"state": "completed", "outcome": "INCONCLUSIVE", "run_id": run}

    class Evidence:
        def __init__(self, token, project):
            assert token == "test-read-token"

        def pull(self, number):
            return metadata(revision(number))

    executor = object()
    monkeypatch.setattr(checks, "_inspect", lambda *args: (
        {"status": "INCONCLUSIVE", "rule": checks.RULE}, None) if args[-1] is executor else pytest.fail())
    options = dict(config=lambda: (PROJECT, SECRET), memory_factory=Memory,
                   github_factory=Evidence, compiler_factory=lambda: executor)
    body, signature, key, _ = delivery(1)
    item = dict(body=base64.b64encode(body).decode(), signature=signature, delivery=key)
    with pytest.raises(checks.CheckError):
        hosted.consume(item, **options)
    assert hosted.consume(item, **options) == "INCONCLUSIVE"
    assert hosted.consume({**item, "delivery": str(uuid4())}, **options) == "COMPLETED"
    assert hosted.consume({**item, "signature": "forged"}, **options) == "REJECTED"
    assert transitions == ["transport-failure", "claim", "finish"]
    assert "test-jwt" not in caplog.text


@pytest.mark.parametrize("mode", ["allow-all", None, "deny-all"])
def test_sandbox_fail_closed_and_cleanup(monkeypatch, mode):
    sdk = pytest.importorskip("vercel.sandbox.sync")
    recorded = []

    @contextmanager
    def create(**options):
        assert options["network_policy"].mode == "deny-all"
        assert options["persistent"] is False and options["env"] == {} and options["ports"] == []
        assert options["execution_time_limit"] == 10 and options["resources"].vcpus == 1
        try:
            yield SimpleNamespace(
                network_policy=SimpleNamespace(mode=mode),
                current_session=SimpleNamespace(network_policy=SimpleNamespace(mode=mode)),
                fs=SimpleNamespace(write_bytes=lambda path, data: recorded.append((path, data))),
                run_command=lambda *a, **kw: SimpleNamespace(
                    returncode=0, stdout=b'3.14.2\n{"kind":"valid"}'))
        finally:
            recorded.append("stopped")

    monkeypatch.setattr(sdk, "create_sandbox", create)
    compiler = sandbox.SandboxCompiler()
    if mode == "deny-all":
        assert compiler(b"x=1", monotonic() + 30) == {"kind": "valid"}
        assert compiler.compiler_version == "3.14.2"
        assert recorded[1] == ("/vercel/sandbox/input", b"x=1")
    else:
        with pytest.raises(sandbox._IsolationUnavailable, match="network isolation"):
            compiler(b"x=1", monotonic() + 30)
        assert recorded == ["stopped"]
    assert recorded[-1] == "stopped"
