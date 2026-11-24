"""Single-worker, staging-only webhook pilot. Check publication is disabled."""
from contextlib import closing
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import argparse
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Protocol

from server import scop_firewall_checks as checks

STAGING = "lbklqqqbmeyseeccdqog"
RETENTION = timedelta(days=14).total_seconds()


class QueueUnavailable(Exception):
    """The queue could not confirm durable acceptance."""


class DeliveryQueue(Protocol):
    def add(self, key: str, body: bytes, signature: str) -> None: ...
    def claim(self) -> tuple[str, bytes, str] | None: ...
    def finish(self, key: str, state: str, result: dict) -> None: ...


class Queue:
    def __init__(self, path):
        self.path = path
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY, body BLOB, signature TEXT,
                    state TEXT NOT NULL, received REAL NOT NULL,
                    updated REAL NOT NULL, result TEXT
                )
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=1)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def add(self, key, body, signature):
        now = time.time()
        try:
            with closing(self.connect()) as db, db:
                db.execute("""
                    INSERT INTO deliveries VALUES (?, ?, ?, 'pending', ?, ?, NULL)
                    ON CONFLICT(id) DO NOTHING
                """, (key, body, signature, now, now))
        except sqlite3.Error as exc:
            raise QueueUnavailable("Durable delivery acceptance failed") from exc

    def claim(self):
        with closing(self.connect()) as db, db:
            return db.execute("""
                UPDATE deliveries SET state='running', updated=?
                WHERE id=(SELECT id FROM deliveries WHERE state='pending' ORDER BY received LIMIT 1)
                RETURNING id, body, signature
            """, (time.time(),)).fetchone()

    def recover(self):
        # A remote claim or finish may already have committed. Hold for inspection.
        with closing(self.connect()) as db, db:
            db.execute("UPDATE deliveries SET state='review', updated=? WHERE state='running'", (time.time(),))

    def finish(self, key, state, result):
        with closing(self.connect()) as db, db:
            db.execute("""
                UPDATE deliveries SET state=?, result=?,
                    body=CASE WHEN ? THEN body ELSE NULL END,
                    signature=CASE WHEN ? THEN signature ELSE NULL END, updated=?
                WHERE id=? AND state='running'
            """, (state, json.dumps(result), state == "review", state == "review", time.time(), key))

    def prune(self):
        with closing(self.connect()) as db, db:
            db.execute("DELETE FROM deliveries WHERE updated<?", (time.time() - RETENTION,))

    def status(self):
        with closing(self.connect()) as db:
            return {state: {"count": count, "oldest_seconds": int(time.time() - oldest)}
                    for state, count, oldest in db.execute(
                        "SELECT state, count(*), min(received) FROM deliveries GROUP BY state")}


def accept_delivery(queue: DeliveryQueue, project, secret, body, signature, delivery, event):
    key, _ = checks.authenticate(body, signature, delivery, event, secret, project)
    queue.add(key, body, signature)
    return key


def receiver(queue, project, secret):
    class Receiver(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def respond(self, code):
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            if self.path != "/webhooks/github":
                return self.respond(404)
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding") is not None:
                return self.respond(400)
            try:
                length = int(lengths[0])
            except ValueError:
                return self.respond(400)
            if length > checks.MAX_WEBHOOK:
                return self.respond(413)
            if length <= 0:
                return self.respond(400)
            try:
                body = self.rfile.read(length)
            except TimeoutError:
                return self.respond(408)
            if len(body) != length:
                return self.respond(400)
            signature = self.headers.get("X-Hub-Signature-256")
            try:
                accept_delivery(queue, project, secret, body, signature,
                                self.headers.get("X-GitHub-Delivery"), self.headers.get("X-GitHub-Event"))
            except checks.CheckError:
                return self.respond(403)
            except QueueUnavailable:
                return self.respond(503)
            return self.respond(202)

    return Receiver


def process(queue: DeliveryQueue, project, secret, memory, github, *, executor=None):
    item = queue.claim()
    if item is None:
        return False
    key, body, signature = item
    try:
        result = checks.analyze(body, signature, key, "pull_request", project=project,
                                secret=secret, memory=memory, github=github, executor=executor)
    except checks.CheckError:
        result = {"status": "REVIEW_REQUIRED"}
    state = "review" if result["status"] in {"ERROR", "REVIEW_REQUIRED", "DUPLICATE"} else "done"
    queue.finish(key, state, result)
    return True


def credential(name):
    directory = Path(os.environ["CREDENTIALS_DIRECTORY"])
    return (directory / name).read_text().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("receive", "work", "status"))
    mode = parser.parse_args().mode
    os.umask(0o007)
    queue = Queue(os.environ["REIVRO_QUEUE"])
    if mode == "status":
        print(json.dumps(queue.status()))
        return
    if os.environ["REIVRO_STAGING_REF"] != STAGING:
        raise SystemExit("Pilot requires the authorized staging project")
    project = checks.Project(os.environ["REIVRO_REPOSITORY"],
                             int(os.environ["REIVRO_REPOSITORY_ID"]),
                             int(os.environ["REIVRO_INSTALLATION_ID"]),
                             os.environ["REIVRO_TRUSTED_BASE"])
    if project.repository != "sovereis/reivro-firewall-demo" or project.base_ref != "main":
        raise SystemExit("Pilot requires the authorized demo repository and branch")
    secret = credential("webhook").encode()
    if len(secret) < 32:
        raise SystemExit("Webhook credential is too short")
    if mode == "receive":
        with HTTPServer(("127.0.0.1", 8088), receiver(queue, project, secret)) as server:
            server.serve_forever()
        return
    with open(queue.path + ".worker.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        queue.recover()
        while True:
            queue.prune()
            if not queue.status().get("pending"):
                time.sleep(2)
                continue
            memory = checks.StagingMemory(STAGING, credential("publishable-key"), credential("worker-jwt"))
            github = checks.GitHubEvidence(credential("github-installation-token"), project)
            process(queue, project, secret, memory, github)


if __name__ == "__main__":
    main()
