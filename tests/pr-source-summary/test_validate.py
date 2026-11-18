"""Regression tests for suite coverage and evidence validation."""

import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import validate


DIRECTORY = Path(__file__).parent
PATCH = """diff --git a/src/flask/sansio/app.py b/src/flask/sansio/app.py
--- a/src/flask/sansio/app.py
+++ b/src/flask/sansio/app.py
@@ -1,3 +1,3 @@
     context
-    def select_jinja_autoescape(self, filename: str) -> bool:
+    def select_jinja_autoescape(self, filename: str | None) -> bool:
++++ content beginning with three plus signs"""


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((DIRECTORY / "pallets-flask-5808.json").read_text())
        self.diff = self.record["verified_facts"][1]["sources"][0]

    def verify_excerpt(self, excerpt):
        self.diff["excerpt"] = excerpt
        identity, sources = validate.validate(self.record)
        metadata = {"html_url": self.record["pr_url"], "merged": True,
                    "body": self.record["verified_facts"][2]["sources"][0]["excerpt"]}
        files = [{"filename": self.diff["locator"], "patch": PATCH}]
        with patch.object(validate, "github_json", side_effect=[metadata, files]):
            validate.verify_live(identity, sources)

    def test_missing_diff_prefix(self):
        for excerpt in ("select_jinja_autoescape", self.diff["excerpt"].split("\n")[1][1:]):
            with self.subTest(excerpt=excerpt):
                with self.assertRaisesRegex(ValueError, "diff excerpt|evidence is absent"):
                    self.verify_excerpt(excerpt)

    def test_incorrect_diff_prefix(self):
        added = self.diff["excerpt"].split("\n")[1]
        with self.assertRaisesRegex(ValueError, "evidence is absent"):
            self.verify_excerpt("-" + added[1:])

    def test_incomplete_diff_line(self):
        with self.assertRaisesRegex(ValueError, "evidence is absent"):
            self.verify_excerpt("+    def select_jinja_autoescape")

    def test_file_header_is_not_evidence(self):
        with self.assertRaisesRegex(ValueError, "evidence is absent"):
            self.verify_excerpt("+++ b/src/flask/sansio/app.py")

    def test_excerpt_cannot_span_hunks(self):
        self.assertFalse(validate.diff_excerpt_matches(
            "@@ -1 +1 @@\n-a\n+b\n@@ -3 +3 @@\n-c\n+d", "+b\n-c"
        ))

    def test_complete_changed_and_context_lines(self):
        self.verify_excerpt("     context\n" + self.diff["excerpt"])
        self.verify_excerpt("++++ content beginning with three plus signs")

    def test_complete_line_after_no_newline_marker(self):
        diff = "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new"
        self.assertTrue(validate.diff_excerpt_matches(diff, "+new"))
        self.assertFalse(validate.diff_excerpt_matches(diff, "-old\n+new"))

    def test_incorrect_source_references(self):
        valid_url = self.diff["url"]
        for url in (valid_url.replace("/pull/5808", "/pull/5898"),
                    self.record["pr_url"] + "/files#diff-" + "0" * 64):
            with self.subTest(url=url):
                self.diff["url"] = url
                with self.assertRaisesRegex(ValueError, "source URL does not match"):
                    validate.validate(self.record)

    def test_missing_required_fields(self):
        for field in self.record:
            with self.subTest(field=field):
                incomplete = self.record.copy()
                del incomplete[field]
                with self.assertRaisesRegex(ValueError, "missing record fields"):
                    validate.validate(incomplete)
        for field in self.diff:
            with self.subTest(source_field=field):
                incomplete = copy.deepcopy(self.record)
                del incomplete["verified_facts"][1]["sources"][0][field]
                with self.assertRaisesRegex(ValueError, "invalid source fields"):
                    validate.validate(incomplete)


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.paths = sorted(DIRECTORY.glob("*.json"))

    def run_validator(self, paths):
        output = io.StringIO()
        with patch("sys.argv", ["validate.py", *map(str, paths)]), contextlib.redirect_stdout(output):
            status = validate.main()
        return status, output.getvalue()

    def assert_rejected(self, paths, message):
        status, output = self.run_validator(paths)
        self.assertEqual(status, 1, output)
        self.assertIn(message, output)
        self.assertNotIn("PASS ", output)

    def test_missing_required_record(self):
        paths = [path for path in self.paths if path.name != "pallets-flask-5808.json"]
        self.assert_rejected(paths, "missing required PR: pallets/flask#5808")

    def test_duplicate_pr_under_different_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            alternate = Path(directory) / "another-name.json"
            alternate.write_bytes((DIRECTORY / "pallets-flask-5808.json").read_bytes())
            self.assert_rejected([*self.paths, alternate], "duplicate PR: pallets/flask#5808")

    def test_unexpected_pr(self):
        with tempfile.TemporaryDirectory() as directory:
            alternate = Path(directory) / "pallets-flask-5808.json"
            original = (DIRECTORY / alternate.name).read_text()
            alternate.write_text(original.replace("/pull/5808", "/pull/9999"))
            paths = [path for path in self.paths if path.name != alternate.name]
            self.assert_rejected([*paths, alternate], "unexpected PR: pallets/flask#9999")

    def test_suite_accepts_valid_records_with_different_names(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index, original in enumerate(self.paths):
                alternate = Path(directory) / f"record-{index}.json"
                alternate.write_bytes(original.read_bytes())
                paths.append(alternate)
            status, output = self.run_validator(paths)
            self.assertEqual(status, 0, output)
            self.assertIn("3 passed, 0 blocked, 0 failed", output)


if __name__ == "__main__":
    unittest.main()
