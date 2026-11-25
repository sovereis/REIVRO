"""Hosted pilot transport. The worker only has an analysis capability."""
import asyncio
import base64
import binascii
import logging
import os

from . import scop_firewall_checks as checks
from .scop_firewall_pilot import STAGING
from .scop_firewall_sandbox import SandboxCompiler

TOPIC = "reivro-firewall-dry-run"
WEBHOOK = "/webhooks/github"
MAX_CALLBACK = 4 * ((checks.MAX_WEBHOOK + 2) // 3) + 4096
LOG = logging.getLogger(__name__)


class InvalidRequest(Exception):
    def __init__(self, status):
        self.status = status


def configuration():
    if os.environ.get("REIVRO_MODE") != "dry-run" or os.environ.get("REIVRO_STAGING_REF") != STAGING:
        raise ValueError("Hosted pilot configuration denied")
    project = checks.Project("sovereis/reivro-firewall-demo",
                             int(os.environ["REIVRO_REPOSITORY_ID"]),
                             int(os.environ["REIVRO_INSTALLATION_ID"]), "main")
    secret = os.environ["REIVRO_WEBHOOK_SECRET"].encode()
    if len(secret) < 32:
        raise ValueError("Hosted pilot credential unavailable")
    return project, secret


async def request_body(receive, limit):
    body = bytearray()
    try:
        async with asyncio.timeout(10):
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    raise InvalidRequest(400)
                chunk = message.get("body", b"")
                if len(chunk) > limit - len(body):
                    raise InvalidRequest(413)
                body.extend(chunk)
                if not message.get("more_body"):
                    return bytes(body)
    except TimeoutError:
        raise InvalidRequest(408) from None


def headers_for(scope):
    headers = {}
    for name, value in scope["headers"]:
        if name in headers and (name.startswith((b"x-hub-", b"x-github-"))
                                or name == b"content-type"):
            raise InvalidRequest(400)
        headers[name] = value
    return headers


async def publish(key, body, signature):
    from vercel.queue import DuplicateIdempotencyKeyError, send

    item = {"delivery": key, "body": base64.b64encode(body).decode("ascii"), "signature": signature}
    try:
        async with asyncio.timeout(10):
            message_id = await send(TOPIC, item, idempotency_key=key, retention=3600)
    except DuplicateIdempotencyKeyError:
        return
    if not message_id:
        raise RuntimeError("Queue acceptance not confirmed")


def consume(item, *, config=configuration, memory_factory=checks.StagingMemory,
            github_factory=checks.GitHubEvidence, compiler_factory=SandboxCompiler):
    project, secret = config()
    try:
        encoded = item["body"]
        if not isinstance(encoded, str) or len(encoded) > MAX_CALLBACK:
            raise ValueError
        body = base64.b64decode(encoded, validate=True)
        signature, delivery = item["signature"], item["delivery"]
        key, _ = checks.authenticate(body, signature, delivery, "pull_request", secret, project)
    except (KeyError, TypeError, ValueError, binascii.Error, checks.CheckError):
        return "REJECTED"
    memory = memory_factory(STAGING, os.environ["REIVRO_PUBLISHABLE_KEY"], os.environ["REIVRO_WORKER_JWT"])
    github = github_factory(os.environ["REIVRO_GITHUB_INSTALLATION_TOKEN"], project)
    result = checks.analyze(body, signature, key, "pull_request", project=project, secret=secret,
                            memory=memory, github=github, executor=compiler_factory(), durable=True)
    if result["status"] in {"BUSY", "RETRYABLE"}:
        raise RuntimeError("Dry-run delivery requires retry")
    if result["status"] not in {"COMPLETED", "TERMINAL", "OBSERVED", "VIOLATION",
                                "PASS", "INCONCLUSIVE", "INACTIVE"}:
        raise RuntimeError("Dry-run completion not confirmed")
    if result["status"] == "TERMINAL":
        LOG.warning("dry-run attempt budget exhausted: %s", result["run_id"])
    return result["status"]


def make_app(*, config=configuration, enqueue=publish):
    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                operation = message["type"]
                await send({"type": operation + ".complete"})
                if operation == "lifespan.shutdown":
                    return
        if scope["type"] != "http":
            return
        try:
            if scope["path"] != WEBHOOK:
                raise InvalidRequest(404)
            if scope["method"] != "POST":
                raise InvalidRequest(405)
            project, secret = config()
            headers = headers_for(scope)
            body = await request_body(receive, checks.MAX_WEBHOOK)
            try:
                signature = headers[b"x-hub-signature-256"].decode("ascii")
                delivery = headers[b"x-github-delivery"].decode("ascii")
                event = headers[b"x-github-event"].decode("ascii")
                key, _ = checks.authenticate(body, signature, delivery, event, secret, project)
            except (KeyError, UnicodeError, checks.CheckError):
                raise InvalidRequest(403) from None
            await enqueue(key, body, signature)
            status = 202
        except InvalidRequest as exc:
            status = exc.status
        except Exception:
            LOG.warning("dry-run transport unavailable")
            status = 503
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": b""})

    return app


async def process_message(payload):
    try:
        await asyncio.to_thread(consume, payload)
    except Exception:
        raise RuntimeError("dry-run processing unavailable") from None
