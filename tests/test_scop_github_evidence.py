"""Read-only GitHub evidence adapter contract tests: no live network required."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from server.scop_github_evidence import GITHUB_READ, run_live
from server.scop_runtime import Status


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "pr-source-summary" / "pallets-flask-5808.json"
TASK = "audit a GitHub pull request summary"


def github_response(url):
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    citations = [c for fact in record["verified_facts"] for c in fact["sources"]]
    if url.endswith("/files?per_page=100&page=1"):
        excerpt = next(c["excerpt"] for c in citations if c["kind"] == "diff")
        filename = next(c["locator"] for c in citations if c["kind"] == "diff")
        return [{"filename": filename, "patch": "@@ -1,2 +1,2 @@\n" + excerpt}]
    if "/files?" in url:
        return []
    return {"html_url": record["pr_url"], "merged": True,
            "body": next(c["excerpt"] for c in citations if c["kind"] == "description")}


class GithubEvidenceTests(unittest.TestCase):
    def test_denied_before_reading_or_network(self):
        stream = Mock()
        with patch("server.scop_github_evidence.fetch_json") as fetch:
            for permissions in ((), ("local:read-summary-record",),
                                (GITHUB_READ, "repo:write")):
                with self.subTest(permissions=permissions):
                    result = run_live(TASK, stream, permissions)
                    self.assertEqual(result.status, Status.BLOCKED)
                    self.assertEqual(result.error_code, "permission_denied")
            stream.read.assert_not_called()
            fetch.assert_not_called()

    def test_live_checks_all_citations(self):
        with patch("server.scop_github_evidence.fetch_json", side_effect=github_response) as fetch:
            result = run_live(TASK, io.BytesIO(FIXTURE.read_bytes()), (GITHUB_READ,))
        self.assertEqual(result.status, Status.COMPLETED)
        self.assertEqual(result.offline_validation, "offline_structure")
        self.assertEqual(result.validation_mode, "github_live_evidence")
        self.assertEqual(result.references_checked, 3)
        self.assertEqual(result.references_verified, 3)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([e["status"] for e in result.events],
                         [Status.QUEUED, Status.RUNNING, Status.COMPLETED])

    def test_modified_live_diff_fails_not_completes(self):
        def changed(url):
            answer = github_response(url)
            if isinstance(answer, list):
                answer[0]["patch"] = "@@ -1 +1 @@\n-old\n+new"
            return answer
        with patch("server.scop_github_evidence.fetch_json", side_effect=changed):
            result = run_live(TASK, io.BytesIO(FIXTURE.read_bytes()), (GITHUB_READ,))
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.error_code, "evidence_mismatch")
        self.assertLess(result.references_verified, 3)

    def test_network_outage_blocks_not_completes(self):
        from server.scop_github_evidence import _Unavailable
        with patch("server.scop_github_evidence.fetch_json", side_effect=_Unavailable()):
            result = run_live(TASK, io.BytesIO(FIXTURE.read_bytes()), (GITHUB_READ,))
        self.assertEqual(result.status, Status.BLOCKED)
        self.assertEqual(result.error_code, "github_unavailable")

    def test_invalid_record_does_not_reach_network(self):
        with patch("server.scop_github_evidence.fetch_json") as fetch:
            result = run_live(TASK, io.BytesIO(b"{}"), (GITHUB_READ,))
        self.assertEqual(result.status, Status.FAILED)
        fetch.assert_not_called()

    def test_unsupported_skill_does_not_reach_network(self):
        with patch("server.scop_github_evidence.fetch_json") as fetch:
            result = run_live("propose regression tests for a software bug",
                              io.BytesIO(FIXTURE.read_bytes()), (GITHUB_READ,))
        self.assertEqual(result.status, Status.BLOCKED)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
