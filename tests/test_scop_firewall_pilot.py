from contextlib import closing
from http.client import HTTPConnection
from http.server import HTTPServer
import json
from threading import Thread
import time
from uuid import uuid4

from server import scop_firewall_checks as checks
from server import scop_firewall_pilot as pilot
from test_scop_firewall_checks import PROJECT, SECRET, delivery, metadata, revision


def test_receiver_validates_before_commit_and_deduplicates(tmp_path):
    queue = pilot.Queue(tmp_path / "queue.sqlite")
    body, signature, key, event = delivery(1)
    with HTTPServer(("127.0.0.1", 0), pilot.receiver(queue, PROJECT, SECRET)) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def send(payload, sig):
                with closing(HTTPConnection(*server.server_address, timeout=5)) as client:
                    client.request("POST", "/webhooks/github", payload, {
                        "X-Hub-Signature-256": sig, "X-GitHub-Delivery": key, "X-GitHub-Event": event,
                    })
                    return client.getresponse().status

            assert send(body, "invalid") == 403
            wrong, signed, _, _ = delivery(1, lambda data: data["installation"].update(id=999))
            assert send(wrong, signed) == 403
            with closing(HTTPConnection(*server.server_address, timeout=5)) as client:
                client.request("POST", "/webhooks/github", headers={
                    "Content-Length": str(checks.MAX_WEBHOOK + 1),
                })
                assert client.getresponse().status == 413
            assert not queue.status()
            assert send(body, signature) == 202
            assert send(body, signature) == 202
            reopened = pilot.Queue(queue.path)
            assert reopened.claim() == (key, body, signature)
            assert reopened.claim() is None
        finally:
            server.shutdown()
            thread.join()


def test_worker_recovery_holds_interrupted_job_and_drains_pending(tmp_path, monkeypatch):
    queue = pilot.Queue(tmp_path / "queue.sqlite")
    body, signature, first, _ = delivery(1)
    queue.add(first, body, signature)
    assert queue.claim()[0] == first
    body, signature, second, _ = delivery(2)
    queue.add(second, body, signature)

    queue = pilot.Queue(queue.path)
    queue.recover()
    assert queue.status()["review"]["count"] == 1

    run = str(uuid4())

    class GitHub:
        def pull(self, number):
            return metadata(revision(number))

        def publish(self, payload):
            raise AssertionError("Check publication must remain disabled")

    class Memory:
        def dispatch(self, action, request):
            if action == "claim":
                return {"run_id": run}
            assert action == "finish" and request["run_id"] == run
            return {"run_id": run, "outcome": "INCONCLUSIVE"}

    monkeypatch.setattr(checks, "_inspect", lambda *args: (
        {"status": "INCONCLUSIVE", "rule": checks.RULE}, None))
    assert pilot.process(queue, PROJECT, SECRET, Memory(), GitHub())
    assert not pilot.process(queue, PROJECT, SECRET, Memory(), GitHub())
    with closing(queue.connect()) as db, db:
        state, stored_body, result = db.execute(
            "SELECT state, body, result FROM deliveries WHERE id=?", (second,)).fetchone()
        assert state == "done" and stored_body is None and json.loads(result)["run_id"] == run
        db.execute("UPDATE deliveries SET updated=?", (time.time() - pilot.RETENTION - 1,))
    queue.prune()
    assert not queue.status()
