"""Offline behavior checks and an opt-in real public GitHub CLI test."""

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import TestCase, skipUnless
from unittest.mock import patch

from server.scop_github_evidence import GITHUB_READ, _Unavailable
from server.scop_pr_summary import _build_record, summarize


URL = "https://github.com/pallets/flask/pull/5808"
PERMISSIONS = (GITHUB_READ,)
FILE = "src/example.py"


def evidence(url, _deadline):
    if "/files?" in url:
        return [{"filename": FILE, "patch": "@@ -1 +1 @@\n-old\n+new", "additions": 1, "deletions": 1}]
    return {"html_url": URL, "merged": True, "changed_files": 1,
            "body": "<!-- Motivation: template -->\n# Change\nChanges help.\n## Why\nReduce ambiguity."}


class PrSummaryTests(TestCase):
    def test_permission_denial_and_invalid_url_do_not_fetch(self):
        with patch("server.scop_github_evidence.fetch_json") as fetch:
            for permissions in ((), (GITHUB_READ, "repo:write")):
                denied = summarize(URL, permissions)
                self.assertEqual((denied.status, denied.error_code), ("blocked", "permission_denied"))
                self.assertIsNone(denied.summary)
            for url in (URL + "?redirect=1", URL.replace("github.com", "github.com.example.org"),
                        "https://github.com/../flask/pull/5808"):
                self.assertEqual(summarize(url, PERMISSIONS).error_code, "invalid_pr_url")
            fetch.assert_not_called()

    def test_builds_schema_valid_verified_summary_from_public_response_shape(self):
        with patch("server.scop_github_evidence.fetch_json", side_effect=evidence) as fetch:
            result = summarize(URL, PERMISSIONS)
        self.assertEqual(result.status, "completed", result.error_message)
        self.assertEqual(result.offline_validation, "offline_structure")
        self.assertEqual(result.references_checked, 4)
        self.assertEqual(result.references_verified, 4)
        self.assertEqual([event["status"] for event in result.events], ["queued", "running", "completed"])
        self.assertEqual(result.summary["assumptions"], [])
        facts = result.summary["verified_facts"]
        self.assertIn("merged = true", facts[0]["claim"])
        self.assertEqual(facts[1]["claim"], "Author-reported motivation excerpt: Reduce ambiguity.")
        self.assertEqual([s["excerpt"] for s in facts[2]["sources"]], ["-old", "+new"])
        self.assertEqual(fetch.call_count, 2)

    def test_missing_body_context_is_not_invented(self):
        def no_body(url, deadline):
            response = evidence(url, deadline)
            if isinstance(response, dict):
                response.update(body=None, merged=False)
            return response
        with patch("server.scop_github_evidence.fetch_json", side_effect=no_body):
            result = summarize(URL, PERMISSIONS)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.references_verified, 3)
        self.assertIn("merged = false", result.summary["verified_facts"][0]["claim"])

    def test_mismatch_publishes_no_summary(self):
        def corrupt(*args):
            record = _build_record(*args)
            record["verified_facts"][-1]["sources"][-1]["excerpt"] = "+absent"
            return record
        with patch("server.scop_github_evidence.fetch_json", side_effect=evidence):
            with patch("server.scop_pr_summary._build_record", side_effect=corrupt):
                result = summarize(URL, PERMISSIONS)
        self.assertEqual((result.status, result.error_code), ("failed", "evidence_mismatch"))
        self.assertEqual((result.references_checked, result.references_verified), (4, 3))
        self.assertIsNone(result.summary)

    def test_missing_truncated_or_oversized_evidence_blocks(self):
        for scenario in ("missing file", "missing patch", "truncated patch", "file cap", "rate limit"):
            def incomplete(url, deadline):
                if scenario == "rate limit":
                    raise _Unavailable("GitHub evidence could not be retrieved")
                response = evidence(url, deadline)
                if isinstance(response, dict) and scenario == "file cap":
                    response["changed_files"] = 301
                if isinstance(response, list):
                    if scenario == "missing file":
                        return []
                    if scenario == "missing patch":
                        del response[0]["patch"]
                    if scenario == "truncated patch":
                        response[0]["additions"] = 2
                return response
            with self.subTest(scenario=scenario):
                with patch("server.scop_github_evidence.fetch_json", side_effect=incomplete):
                    result = summarize(URL, PERMISSIONS)
                self.assertEqual((result.status, result.error_code), ("blocked", "github_unavailable"))
                self.assertIsNone(result.summary)

    @skipUnless(os.environ.get("SCOP_LIVE_TESTS") == "1", "set SCOP_LIVE_TESTS=1 for public GitHub")
    def test_cli_generates_summary_from_real_public_pr(self):
        result = subprocess.run(
            [sys.executable, "-B", "-m", "server.scop_pr_summary", URL, "--permission", GITHUB_READ],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=50,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["references_verified"], 4)
        self.assertEqual({ref["kind"] for ref in payload["evidence_references"]}, {"metadata", "description", "diff"})
        claims = payload["summary"]["verified_facts"]
        self.assertTrue(any("select_jinja_autoescape" in fact["claim"] and "str | None" in fact["claim"]
                            for fact in claims))
