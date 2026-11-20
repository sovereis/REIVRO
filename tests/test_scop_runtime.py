import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from server.scop_runtime import MAX_RECORD_BYTES, READ_RECORD, Status, TaskRequest, run


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "pr-source-summary" / "pallets-flask-5808.json"
TASK = "audit a GitHub pull request summary"


class RuntimeTests(unittest.TestCase):
    def test_permission_denied_before_discovery_or_input(self):
        source = Mock()
        with patch("server.scop_runtime.discover") as discover:
            for permissions in ((), ("repo:write",), (READ_RECORD, "network:read")):
                with self.subTest(permissions=permissions):
                    result = run(TaskRequest(TASK, permissions), source)
                    self.assertEqual(result.status, Status.BLOCKED)
                    self.assertEqual(result.error.code, "permission_denied")
                    self.assertEqual([event.status for event in result.logs], [Status.QUEUED, Status.BLOCKED])
            discover.assert_not_called()
        source.read.assert_not_called()

    def test_unsupported_skill_and_no_match_do_not_read_input(self):
        source = Mock()
        for task, skill in (
            ("propose regression tests for a software bug", "bug-regression-test"),
            ("unrelated bananas", None),
            ("a bug PR", "bug-regression-test"),
        ):
            with self.subTest(task=task):
                result = run(TaskRequest(task), source)
                self.assertEqual(result.status, Status.BLOCKED)
                self.assertEqual(result.skill, skill)
                self.assertEqual(result.error.code, "no_adapter")
        source.read.assert_not_called()

    def test_malformed_or_oversized_input_fails(self):
        for raw in (b"not-json", b"\xff", b"{}", b" " * (MAX_RECORD_BYTES + 1)):
            with self.subTest(size=len(raw)):
                result = run(TaskRequest(TASK), io.BytesIO(raw))
                self.assertEqual(result.status, Status.FAILED)
                self.assertEqual(result.error.code, "invalid_input")
                self.assertEqual([e.status for e in result.logs], [Status.QUEUED, Status.RUNNING, Status.FAILED])
                self.assertIsNone(result.audit)
                self.assertFalse(result.evidence_references)

    def test_blocked_record_preserves_blocked_outcome(self):
        record = json.loads(FIXTURE.read_bytes())
        record.update(status="blocked", verified_facts=[], blocked_reason="Source unavailable")
        result = run(TaskRequest(TASK), io.BytesIO(json.dumps(record).encode()))
        self.assertEqual(result.status, Status.BLOCKED)
        self.assertEqual(result.error.code, "record_blocked")
        self.assertIsNone(result.audit)

    def test_interrupt_cancels_running_task(self):
        source = Mock()
        source.read.side_effect = KeyboardInterrupt
        result = run(TaskRequest(TASK), source)
        self.assertEqual(result.status, Status.CANCELLED)
        self.assertEqual(result.error.code, "interrupted")
        self.assertEqual([e.status for e in result.logs], [Status.QUEUED, Status.RUNNING, Status.CANCELLED])

    def test_read_failure_omits_internal_details(self):
        source = Mock()
        source.read.side_effect = OSError("private diagnostic")
        result = run(TaskRequest(TASK), source)
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.error.code, "read_failed")
        self.assertNotIn("private diagnostic", result.error.message)

    def test_audit_uses_no_process_or_network(self):
        record = json.loads(FIXTURE.read_bytes())
        record["executor"] = "untrusted executor name"
        raw = json.dumps(record).encode()
        with patch("socket.socket", side_effect=AssertionError("network access")) as network:
            with patch("subprocess.Popen", side_effect=AssertionError("process launch")) as process:
                result = run(TaskRequest(TASK), io.BytesIO(raw))
        self.assertEqual(result.status, Status.COMPLETED)
        network.assert_not_called()
        process.assert_not_called()

    def test_cli_audits_real_record_and_rejects_bad_reference(self):
        record = json.loads(FIXTURE.read_bytes())
        cmd = [sys.executable, "-B", "-m", "server.scop_runtime", TASK]
        with tempfile.TemporaryDirectory() as directory:
            # Run outside the repository to verify discovery uses the installed root.
            env = {"PYTHONPATH": str(ROOT)}
            ok = subprocess.run(cmd, input=FIXTURE.read_bytes(), capture_output=True,
                                cwd=directory, env=env, timeout=10)
            self.assertEqual(ok.returncode, 0, ok.stderr.decode())
            payload = json.loads(ok.stdout)
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["skill"], "pr-source-summary")
            self.assertEqual(payload["audit"], {
                "pr_url": record["pr_url"], "claims_checked": 3, "references_checked": 3,
            })
            self.assertEqual(payload["evidence_references"], [
                {key: ref[key] for key in ("kind", "url", "locator")}
                for fact in record["verified_facts"] for ref in fact["sources"]
            ])
            self.assertEqual([e["status"] for e in payload["logs"]], ["queued", "running", "completed"])
            times = [e["elapsed_ms"] for e in payload["logs"]]
            self.assertEqual(times, sorted(times))
            self.assertEqual(payload["duration_ms"], times[-1])
            self.assertIsNone(payload["error"])
            self.assertTrue(payload["limitations"])

            record["verified_facts"][0]["sources"][0]["url"] += "/incorrect"
            bad = subprocess.run(cmd, input=json.dumps(record).encode(), capture_output=True,
                                 cwd=directory, env=env, timeout=10)
            self.assertEqual(bad.returncode, 1, bad.stderr.decode())
            payload = json.loads(bad.stdout)
            self.assertEqual(payload["error"]["code"], "invalid_input")
            self.assertIn("source URL does not match", payload["error"]["message"])
            self.assertEqual(list(Path(directory).iterdir()), [])
