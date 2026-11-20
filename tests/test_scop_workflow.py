"""Workflow regression checks with an opt-in public GitHub CLI test."""

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import UUID

from server.scop_github_evidence import GITHUB_READ, _Unavailable
from server.scop_pr_summary import _build_record
from server.scop_workflow import WorkflowRequest, run_workflow


URL = "https://github.com/pallets/flask/pull/5808"
REQUEST = WorkflowRequest(URL, (GITHUB_READ,))
FETCH = "server.scop_github_evidence.fetch_json"


def evidence(url, _deadline):
    if "/files?" in url:
        return [{"filename": "example.py", "patch": "@@ -1 +1 @@\n-old\n+new",
                 "additions": 1, "deletions": 1}]
    return {"html_url": URL, "merged": True, "changed_files": 1, "body": "Why: Improve clarity."}


class WorkflowTests(TestCase):
    def test_complete_workflow_records_identity_and_durations(self):
        with patch(FETCH, side_effect=evidence) as fetch:
            result = run_workflow(REQUEST)
            second = run_workflow(REQUEST)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.skill, "pr-source-summary")
        self.assertEqual(result.summary["pr_url"], URL)
        self.assertEqual((result.references_checked, result.references_verified), (4, 4))
        self.assertEqual(len(result.evidence_references), 4)
        self.assertEqual(UUID(result.execution_id).version, 4)
        self.assertNotEqual(result.execution_id, second.execution_id)
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual([event["status"] for event in result.events], ["queued", "running", "completed"])
        times = [event["elapsed_ms"] for event in result.events]
        self.assertEqual(times, sorted(times))
        self.assertEqual(times[-1], result.duration_ms)
        previous = ()
        for name, step in result.steps.items():
            self.assertEqual(step.requires, previous)
            self.assertEqual(step.status, "completed")
            self.assertGreaterEqual(step.duration_ms, 0)
            self.assertLessEqual(step.duration_ms, result.duration_ms)
            previous = (name,)

    def test_invalid_url_denied_permissions_and_unsupported_skill_never_fetch(self):
        cases = (
            (WorkflowRequest(URL), "blocked", "permission_denied", "validate_request"),
            (WorkflowRequest(URL, (GITHUB_READ, "repo:write")), "blocked", "permission_denied", "validate_request"),
            (WorkflowRequest(URL + "?x=y", (GITHUB_READ,)), "failed", "invalid_pr_url", "validate_request"),
            (WorkflowRequest(URL, (GITHUB_READ,), "propose regression tests for a software bug"),
             "blocked", "unsupported_skill", "select_skill"),
        )
        for request, status, error, step in cases:
            with self.subTest(error=error):
                with patch(FETCH) as fetch:
                    result = run_workflow(request)
                fetch.assert_not_called()
                self.assertEqual((result.status, result.error_code), (status, error))
                self.assertEqual(result.steps[step].status, status)
                self.assertEqual(result.steps["generate_summary"].status, "queued")
                self.assertIsNone(result.steps["generate_summary"].duration_ms)
                self.assertIsNone(result.summary)
                if error == "unsupported_skill":
                    self.assertEqual(result.skill, "bug-regression-test")

    def test_unavailable_incomplete_and_interrupted_generation_stop_workflow(self):
        for failure, expected in (
            (_Unavailable("GitHub evidence could not be retrieved"), "blocked"),
            (KeyboardInterrupt(), "cancelled"),
            (RuntimeError("internal diagnostic"), "failed"),
            ([evidence(URL, None), []], "blocked"),
        ):
            with self.subTest(expected=expected):
                with patch(FETCH, side_effect=failure):
                    result = run_workflow(REQUEST)
                self.assertEqual(result.status, expected)
                self.assertEqual(result.steps["generate_summary"].status, expected)
                self.assertEqual(result.steps["verify_evidence"].status, "queued")
                self.assertIsNone(result.steps["verify_evidence"].duration_ms)
                self.assertIsNone(result.summary)
                self.assertNotIn("internal diagnostic", result.error_message)

    def test_mismatch_fails_verification_and_withholds_summary(self):
        def draft_with_wrong_citation(*args):
            record = _build_record(*args)
            record["verified_facts"][-1]["sources"][-1]["excerpt"] = "+absent"
            return record
        with patch(FETCH, side_effect=evidence):
            with patch("server.scop_pr_summary._build_record", side_effect=draft_with_wrong_citation):
                result = run_workflow(REQUEST)
        self.assertEqual((result.status, result.error_code), ("failed", "evidence_mismatch"))
        self.assertEqual(result.steps["generate_summary"].status, "completed")
        self.assertEqual(result.steps["verify_evidence"].status, "failed")
        self.assertEqual((result.references_checked, result.references_verified), (4, 3))
        self.assertEqual(result.evidence_references, ())
        self.assertIsNone(result.summary)

    @skipUnless(os.environ.get("SCOP_LIVE_TESTS") == "1", "set SCOP_LIVE_TESTS=1 for public GitHub")
    def test_cli_completes_real_public_pr_without_writes(self):
        # Install an audit hook inside the actual CLI process to detect writes
        # even if a broad runtime exception handler would otherwise hide them.
        guarded_cli = """
import os, sys
from server.scop_workflow import main
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
        run = subprocess.run(
            [sys.executable, "-B", "-c", guarded_cli, URL, "--permission", GITHUB_READ],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=50,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stderr, "")
        result = json.loads(run.stdout)
        self.assertEqual((result["status"], result["references_verified"]), ("completed", 4))
        self.assertTrue(all(step["status"] == "completed" for step in result["steps"].values()))
        self.assertTrue(any("select_jinja_autoescape" in fact["claim"]
                            for fact in result["summary"]["verified_facts"]))
