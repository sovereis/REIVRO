"""Regression tests for proposal evidence and execution claims."""

import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from validate import validate, verify_sources


class ProposalValidationTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(
            Path(__file__).with_name("pytest-11758.json").read_text(encoding="utf-8")
        )

    def test_complete_record_and_exact_quotes(self):
        validate(self.record)
        body = "\r\n".join(item["quote"] for item in self.record["evidence"])
        fetch = Mock(return_value=body)
        verify_sources(self.record, fetch)
        fetch.assert_called_once_with(self.record["issue_url"])

    def test_incomplete_bug_evidence(self):
        for missing_role in ("trigger", "symptom"):
            with self.subTest(missing_role=missing_role):
                original = self.record.copy()
                original["evidence"] = [
                    item for item in self.record["evidence"] if item["role"] != missing_role
                ]
                with self.assertRaisesRegex(ValueError, "incomplete evidence"):
                    validate(original)

    def test_missing_source_reference(self):
        del self.record["evidence"][0]["url"]
        with self.assertRaisesRegex(ValueError, "source evidence has missing"):
            validate(self.record)

    def test_unrelated_primary_issue(self):
        self.record["issue_url"] = "https://github.com/pytest-dev/pytest/issues/1"
        with self.assertRaisesRegex(ValueError, "primary issue reference"):
            validate(self.record)

    def test_unsupported_quotation(self):
        validate(self.record)
        with self.assertRaisesRegex(ValueError, "unsupported evidence quotation"):
            verify_sources(self.record, lambda _: "No matching evidence.")

    def test_unsupported_execution_claim(self):
        self.record["upstream_execution"]["status"] = "passed"
        with self.assertRaisesRegex(ValueError, "unsupported upstream execution claim"):
            validate(self.record)

    def test_unsupported_fact_field(self):
        self.record["evidence"][0]["claim"] = "The fix eliminated every related failure."
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            validate(self.record)

    def test_unlabeled_inference(self):
        self.record["proposal"]["rationale"] = "The issue proves the proposed result."
        with self.assertRaisesRegex(ValueError, "must identify inferred behavior"):
            validate(self.record)


if __name__ == "__main__":
    unittest.main()
