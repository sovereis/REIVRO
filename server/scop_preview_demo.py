"""Exercise the preview with disposable commits and synthetic agent declarations."""
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

from .scop_preview import execute, parser


def demo():
    project = "synthetic/preview"
    steps = []
    commands = parser()

    with TemporaryDirectory(prefix="reivro-preview-") as directory:
        root = Path(directory)
        checkout = root / "project"
        checkout.mkdir()
        options = ["--project", project, "--store", str(root / "operator"), "--checkout", str(checkout)]

        def git(*args):
            return subprocess.check_output(
                ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-C", checkout, *args],
                env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                     "GIT_AUTHOR_NAME": "Synthetic", "GIT_AUTHOR_EMAIL": "demo@example.invalid",
                     "GIT_COMMITTER_NAME": "Synthetic", "GIT_COMMITTER_EMAIL": "demo@example.invalid"},
                text=True, timeout=10,
            ).strip()

        def commit(name):
            git("add", "--", ".")
            git("commit", "--quiet", "-m", name)
            return git("rev-parse", "HEAD")

        def run(name, expected, *args, payload=None):
            started = perf_counter()
            result = execute(commands.parse_args([*options, *args]), payload)
            if result["status"] != expected:
                raise ValueError("Demo step did not produce its expected result")
            steps.append({"name": name, "status": expected, "ms": round((perf_counter() - started) * 1000, 3)})
            return result

        def new_task(base):
            return {"version": 1, "project": project, "task_id": str(uuid4()), "base_sha": base,
                    "objective": "Add the required project documentation.",
                    "allowed_paths": ["guide.txt", "notes.txt"], "protected_paths": [],
                    "criteria": [{"kind": "exists", "path": "guide.txt"}]}

        def claim(contract, agent, head):
            return {"version": 1, "project": project, "agent": agent, "task_id": contract["task_id"],
                    "event_id": str(uuid4()), "head_sha": head, "pr": 1}

        started = perf_counter()
        git("init", "--quiet", "--template=", "--object-format=sha1")
        (checkout / "notes.txt").write_text("Disposable example.\n")
        first = new_task(commit("Create demo project"))
        run("Initialize project", "READY", "init")
        setup_ms = (perf_counter() - started) * 1000
        approved = run("Approve task contract", "APPROVED", "task", "approve", payload=first)
        (checkout / "notes.txt").write_text("First change.\n")
        original = claim(first, "codex", commit("First synthetic submission"))
        run("Verify incomplete work", "INCOMPLETE", "verify", approved["digest"], payload=original)
        first_verification_ms = (perf_counter() - started) * 1000
        finding = run("Capture evidence", "FINDING_RECORDED", "review", "capture", original["event_id"],
                      "--criterion", "0")["finding_id"]
        reason = ["--reason", "Synthetic operator decision for the demo"]
        run("Confirm the finding", "FINDING_CONFIRMED", "review", "confirm", finding, *reason)
        protection = run("Propose a reusable protection", "PROPOSED", "protect", "propose", finding)["protection_id"]
        run("Approve and export by digest", "EXPORTED", "protect", "approve", protection, *reason)

        second = new_task(original["head_sha"])
        approved = run("Approve the second task", "APPROVED", "task", "approve", payload=second)
        (checkout / "notes.txt").write_text("Second change.\n")
        repeated = claim(second, "cursor", commit("Second synthetic submission"))
        report = run("Detect the policy violation", "POLICY_VIOLATION", "verify", approved["digest"],
                     payload=repeated)
        if not report["policy"]["recurrence"]:
            raise ValueError("Demo recurrence was not confirmed")
        run("Authorize correction", "POLICY_VIOLATION", "authorize-correction", repeated["event_id"])
        (checkout / "guide.txt").write_text("Required project documentation.\n")
        corrected = claim(second, "cursor", commit("Add the required guide"))
        result = run("Verify authorized correction", "VERIFIED", "verify", approved["digest"],
                     "--after-correction", repeated["event_id"], payload=corrected)
        if not result["correction"]["verified"]:
            raise ValueError("Demo correction was not verified")
        run("Revoke the protection", "REVOKED", "revoke", protection, *reason)
        renamed = claim(second, "cursor", corrected["head_sha"])
        result = run("Verify after revocation", "VERIFIED", "verify", approved["digest"], payload=renamed)
        if result["policies"]:
            raise ValueError("Revoked protection remains in effect")
    return {"status": "DEMO_PASSED", "synthetic": True, "steps": steps,
            "confirmed_recurrence": True, "setup_ms": round(setup_ms, 3),
            "first_verification_ms": round(first_verification_ms, 3)}
