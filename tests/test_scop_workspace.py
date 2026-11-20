"""Tests for the Workspace JSON boundary and its public GitHub example."""

from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch
from uuid import UUID

from server.scop_github_evidence import GITHUB_READ, _Unavailable
from server.scop_pr_summary import _build_record
from server.scop_workspace import MAX_REQUEST_BYTES, handle_request


URL = "https://github.com/pallets/flask/pull/5808"
FETCH = "server.scop_github_evidence.fetch_json"
GRANT = {"pr_url": URL, "permissions": [GITHUB_READ]}


def evidence(url, _deadline):
    if "/files?" in url:
        return [{"filename": "example.py", "patch": "@@ -1 +1 @@\n-old\n+new",
                 "additions": 1, "deletions": 1}]
    return {"html_url": URL, "merged": True, "changed_files": 1, "body": "Why: Improve clarity."}


def submit(payload):
    return handle_request(io.BytesIO(json.dumps(payload).encode()))


class WorkspaceTests(TestCase):
    def test_rejects_bad_transport_without_dispatch(self):
        malformed = (b"", b"\xff", b"[]", b"{}", b'{"pr_url": 1}',
                     b'{"pr_url":"a","pr_url":"b"}', b'{"pr_url":"a","command":"x"}',
                     b'{"pr_url":"a","permissions":"yes"}', b'{"pr_url":"a","task":[]}',
                     b" " * (MAX_REQUEST_BYTES + 1))
        with patch("server.scop_workspace.run_workflow") as workflow:
            for raw in malformed:
                with self.subTest(size=len(raw)):
                    code, response = handle_request(io.BytesIO(raw))
                    self.assertEqual(code, 1)
                    self.assertEqual(response.request_error.code, "invalid_request")
                    self.assertIsNone(response.execution)
        workflow.assert_not_called()

    def test_bad_url_missing_permission_and_unsupported_skill_never_fetch(self):
        cases = (
            ({**GRANT, "pr_url": URL + "?bad=1"}, 1, "failed", "invalid_pr_url"),
            ({"pr_url": URL}, 2, "blocked", "permission_denied"),
            ({**GRANT, "permissions": [GITHUB_READ, "repo:write"]}, 2, "blocked", "permission_denied"),
            ({**GRANT, "task": "propose regression tests for a software bug"}, 2,
             "blocked", "unsupported_skill"),
        )
        for payload, exit_code, status, error in cases:
            with self.subTest(error=error):
                with patch(FETCH) as fetch:
                    code, response = submit(payload)
                fetch.assert_not_called()
                self.assertEqual((code, response.execution.status, response.execution.error_code),
                                 (exit_code, status, error))
                self.assertIsNone(response.request_error)
                self.assertIsNone(response.execution.summary)

    def test_success_preserves_steps_durations_and_citations(self):
        with patch(FETCH, side_effect=evidence) as fetch:
            code, response = submit(GRANT)
        self.assertEqual(code, 0)
        self.assertEqual(response.contract_version, "0.6")
        execution = response.execution
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.skill, "pr-source-summary")
        self.assertEqual(UUID(execution.execution_id).version, 4)
        self.assertGreaterEqual(execution.duration_ms, 0)
        self.assertEqual(len(execution.steps), 4)
        self.assertTrue(all(step.status == "completed" and step.duration_ms >= 0
                            for step in execution.steps.values()))
        citations = [source for fact in execution.summary["verified_facts"] for source in fact["sources"]]
        self.assertEqual(execution.references_verified, 4)
        self.assertEqual([asdict(ref) for ref in execution.evidence_references],
                         [{k: source[k] for k in ("kind", "url", "locator")} for source in citations])
        self.assertEqual(fetch.call_count, 2)

    def test_unavailable_or_contradicted_evidence_withholds_summary(self):
        with patch(FETCH, side_effect=_Unavailable("GitHub evidence could not be retrieved")):
            code, response = submit(GRANT)
        self.assertEqual((code, response.execution.status, response.execution.error_code),
                         (2, "blocked", "github_unavailable"))
        self.assertIsNone(response.execution.summary)

        def corrupt(*args):
            draft = _build_record(*args)
            draft["verified_facts"][-1]["sources"][-1]["excerpt"] = "+absent"
            return draft

        with patch(FETCH, side_effect=evidence):
            with patch("server.scop_pr_summary._build_record", side_effect=corrupt):
                code, response = submit(GRANT)
        self.assertEqual((code, response.execution.status, response.execution.error_code),
                         (1, "failed", "evidence_mismatch"))
        self.assertEqual(response.execution.steps["verify_evidence"].status, "failed")
        self.assertEqual(response.execution.references_verified, 3)
        self.assertIsNone(response.execution.summary)

    def test_transport_and_dispatch_hide_internal_diagnostics(self):
        stream = Mock()
        stream.read.side_effect = ValueError("private diagnostic")
        code, response = handle_request(stream)
        self.assertEqual((code, response.request_error.code), (1, "read_failed"))
        self.assertNotIn("private diagnostic", response.request_error.message)
        with patch("server.scop_workspace.run_workflow", side_effect=RuntimeError("private diagnostic")):
            code, response = submit(GRANT)
        self.assertEqual((code, response.request_error.code), (1, "execution_failed"))
        self.assertNotIn("private diagnostic", response.request_error.message)

    @skipUnless(os.environ.get("SCOP_LIVE_TESTS") == "1", "set SCOP_LIVE_TESTS=1 for public GitHub")
    def test_live_json_boundary_reuses_workflow_without_writes(self):
        guarded_cli = """
import os, sys
from server.scop_workspace import main
write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
def audit(event, args):
    if ((event == "open" and args[2] & write_flags)
            or event in {"os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.symlink",
                         "os.link", "subprocess.Popen", "os.system", "os.exec"}):
        print(f"Forbidden operation: {event}", file=sys.stderr)
        raise AssertionError(event)
sys.addaudithook(audit)
raise SystemExit(main())
"""
        proc = subprocess.run(
            [sys.executable, "-B", "-c", guarded_cli], input=json.dumps(GRANT), text=True,
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=50,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "")
        response = json.loads(proc.stdout)
        self.assertIsNone(response["request_error"])
        execution = response["execution"]
        self.assertEqual((execution["status"], execution["references_verified"]), ("completed", 4))
        self.assertTrue(all(step["status"] == "completed" for step in execution["steps"].values()))
        self.assertTrue(any("select_jinja_autoescape" in fact["claim"]
                            for fact in execution["summary"]["verified_facts"]))
