"""Regression tests for proposal evidence and execution claims."""

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

validator_path = Path(__file__).with_name("validate.py")
spec = spec_from_file_location("scop_bug_regression_test_validator", validator_path)
if spec is None or spec.loader is None:
    raise ImportError(f"Cannot load validator from {validator_path}")
validator = module_from_spec(spec)
spec.loader.exec_module(validator)


class ProposalValidationTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(
            Path(__file__).with_name("pytest-11758.json").read_text(encoding="utf-8")
        )

    def test_complete_record_and_exact_quotes(self):
        validator.validate(self.record)
        body = "\r\n".join(item["quote"] for item in self.record["evidence"])
        fetch = Mock(return_value=body)
        validator.verify_sources(self.record, fetch)
        fetch.assert_called_once_with(self.record["issue_url"])

    def test_incomplete_bug_evidence(self):
        for missing_role in ("trigger", "symptom"):
            with self.subTest(missing_role=missing_role):
                original = self.record.copy()
                original["evidence"] = [
                    item for item in self.record["evidence"] if item["role"] != missing_role
                ]
                with self.assertRaisesRegex(ValueError, "incomplete evidence"):
                    validator.validate(original)

    def test_missing_source_reference(self):
        del self.record["evidence"][0]["url"]
        with self.assertRaisesRegex(ValueError, "source evidence has missing"):
            validator.validate(self.record)

    def test_unrelated_primary_issue(self):
        self.record["issue_url"] = "https://github.com/pytest-dev/pytest/issues/1"
        with self.assertRaisesRegex(ValueError, "primary issue reference"):
            validator.validate(self.record)

    def test_unsupported_quotation(self):
        validator.validate(self.record)
        with self.assertRaisesRegex(ValueError, "unsupported evidence quotation"):
            validator.verify_sources(self.record, lambda _: "No matching evidence.")

    def test_unsupported_execution_claim(self):
        self.record["upstream_execution"]["status"] = "passed"
        with self.assertRaisesRegex(ValueError, "unsupported upstream execution claim"):
            validator.validate(self.record)

    def test_unsupported_fact_field(self):
        self.record["evidence"][0]["claim"] = "The fix eliminated every related failure."
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            validator.validate(self.record)

    def test_unlabeled_inference(self):
        self.record["proposal"]["rationale"] = "The issue proves the proposed result."
        with self.assertRaisesRegex(ValueError, "must identify inferred behavior"):
            validator.validate(self.record)


if __name__ == "__main__":
    unittest.main()
