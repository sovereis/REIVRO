"""Read-only GitHub evidence adapter contract tests: no live network required."""
import io
import json
from pathlib import Path
from time import monotonic
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from server.scop_github_evidence import GITHUB_READ, _NoRedirect, _Unavailable, fetch_json, run_live
from server.scop_runtime import Status


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "pr-source-summary" / "pallets-flask-5808.json"
TASK = "audit a GitHub pull request summary"


def github_response(url, _deadline):
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
        def changed(url, deadline):
            answer = github_response(url, deadline)
            if isinstance(answer, list):
                answer[0]["patch"] = "@@ -1 +1 @@\n-old\n+new"
            return answer
        with patch("server.scop_github_evidence.fetch_json", side_effect=changed):
            result = run_live(TASK, io.BytesIO(FIXTURE.read_bytes()), (GITHUB_READ,))
        self.assertEqual(result.status, Status.FAILED)
        self.assertEqual(result.error_code, "evidence_mismatch")
        self.assertEqual(result.references_checked, 2)
        self.assertEqual(result.references_verified, 1)

    def test_network_outage_blocks_not_completes(self):
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


    def test_page_limit_stops_missing_evidence(self):
        def missing(url, deadline):
            if "/files?" not in url:
                return github_response(url, deadline)
            page = url.rsplit("=", 1)[1]
            return [{"filename": f"unrelated-{page}-{i}.py"} for i in range(100)]
        with patch("server.scop_github_evidence.fetch_json", side_effect=missing) as fetch:
            result = run_live(TASK, io.BytesIO(FIXTURE.read_bytes()), (GITHUB_READ,))
        self.assertEqual(result.status, Status.BLOCKED)
        self.assertEqual(result.references_checked, 0)
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual({call.args[1] for call in fetch.call_args_list}, {fetch.call_args.args[1]})
        self.assertTrue(fetch.call_args.args[0].endswith("page=3"))

    def test_fetch_bounds_and_fixed_get(self):
        url = "https://api.github.com/repos/pallets/flask/pulls/5808"
        with patch("server.scop_github_evidence.build_opener") as build:
            with self.assertRaises(_Unavailable):
                fetch_json(url.replace("api.github.com", "example.com"), monotonic() + 30)
            build.assert_not_called()
            with self.assertRaises(_Unavailable):
                fetch_json(url, monotonic() - 1)
            build.return_value.open.assert_not_called()
            opened = build.return_value.open
            opened.return_value.__enter__.return_value = io.BytesIO(b" " * 9)
            with patch("server.scop_github_evidence._MAX_RESPONSE_BYTES", 8):
                with self.assertRaisesRegex(_Unavailable, "exceeds the evidence limit"):
                    fetch_json(url, monotonic() + 30)
            request = opened.call_args.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.full_url, url)
            self.assertIsNone(request.get_header("Authorization"))
            self.assertEqual(opened.call_args.kwargs["timeout"], 10)
            (redirect_handler,) = build.call_args.args
            self.assertIs(redirect_handler, _NoRedirect)
            self.assertIsNone(redirect_handler().redirect_request(
                request, None, 302, "", {}, "https://example.com"
            ))

    def test_body_read_that_exhausts_budget_is_blocked(self):
        url = "https://api.github.com/repos/pallets/flask/pulls/5808"
        with patch("server.scop_github_evidence.build_opener") as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.read1.return_value = b"{}"
            with patch("server.scop_github_evidence.monotonic", side_effect=[0, 0, 31]):
                with self.assertRaisesRegex(_Unavailable, "exceeded the network time budget"):
                    fetch_json(url, 30)
            response.read1.assert_called_once_with(65_536)

    def test_http_errors_and_invalid_response_are_unavailable(self):
        url = "https://api.github.com/repos/pallets/flask/pulls/5808"
        with patch("server.scop_github_evidence.build_opener") as build:
            opened = build.return_value.open
            opened.return_value.__enter__.return_value = io.BytesIO(b"not JSON")
            with self.assertRaises(_Unavailable):
                fetch_json(url, monotonic() + 30)
            for error in (HTTPError(url, 429, "rate limited", {}, None), TimeoutError()):
                with self.subTest(error=type(error)):
                    opened.side_effect = error
                    with self.assertRaises(_Unavailable):
                        fetch_json(url, monotonic() + 30)


if __name__ == "__main__":
    unittest.main()
