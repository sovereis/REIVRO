"""Exercise the local measurement interface with real workflow stages."""

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from server.scop_measurement import LOCAL_WRITE, MAX_REQUEST_BYTES, handle_request_bytes
from server.scop_github_evidence import GITHUB_READ
from server.scop_pr_summary import _build_record


FETCH = "server.scop_github_evidence.fetch_json"
URL = "https://github.com/pallets/flask/pull/5808"
GRANT = {"pr_url": URL, "permissions": [GITHUB_READ]}


def evidence(url, _deadline):
    if "/files?" in url:
        return [{"filename": "example.py", "patch": "@@ -1 +1 @@\n-old\n+new",
                 "additions": 1, "deletions": 1}]
    return {"html_url": URL, "merged": True, "changed_files": 1, "body": "Why: Improve clarity."}


class MeasurementTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(dir=Path("/tmp").resolve())
        self.addCleanup(temporary.cleanup)
        self.store = Path(temporary.name)

    def call(self, operation, **fields):
        return handle_request_bytes(json.dumps({"operation": operation, **fields}).encode(), self.store)

    def record(self, request=None, expected_code=0):
        with patch(FETCH, side_effect=evidence):
            code, response = self.call("run", request=request or GRANT, permissions=[LOCAL_WRITE])
        self.assertEqual(code, expected_code, response)
        self.assertEqual(response["result"]["workspace"]["contract_version"], "0.6")
        return response["result"]["workspace"]["execution"]["execution_id"]

    def feedback(self, identity, decision="accepted", **fields):
        return self.call("feedback", execution_id=identity, permissions=[LOCAL_WRITE],
                         evaluation={"decision": decision, **fields})

    def test_acceptance_is_explicit_and_keeps_execution_unchanged(self):
        identity = self.record()
        _, before = self.call("get", execution_id=identity)
        self.assertIsNone(before["result"]["feedback"])
        self.assertIsNone(before["result"]["measurement"]["human_review_duration"])
        self.assertFalse(before["result"]["measurement"]["total_observed_task_time"]["complete"])
        review = {"milliseconds": 1200, "provenance": "human_measured"}
        rework = {"milliseconds": 0, "provenance": "human_reported"}
        code, after = self.feedback(identity, review=review, rework=rework, correction_cycles=0)
        self.assertEqual(code, 0)
        old, new = before["result"], after["result"]
        self.assertEqual(old["execution"], new["execution"])
        self.assertEqual(new["execution"]["status"], "completed")
        self.assertEqual(new["feedback"]["evaluation"]["decision"], "accepted")
        self.assertEqual(datetime.fromisoformat(new["feedback"]["timestamp_utc"]).tzinfo, UTC)
        measurement = new["measurement"]
        self.assertEqual(measurement["human_review_duration"], review)
        self.assertEqual(measurement["human_rework_duration"], rework)
        self.assertTrue(measurement["total_observed_task_time"]["complete"])
        self.assertEqual(measurement["total_observed_task_time"]["milliseconds"],
                         round(new["execution"]["duration_ms"] + 1200, 3))
        self.assertEqual(measurement["citation_verification_coverage"]["value"], 1)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in self.store.iterdir()))

    def test_rework_decisions_and_missing_values_are_distinct(self):
        accepted, rework, _ = (self.record() for _ in range(3))
        self.assertEqual(self.feedback(accepted, notes="Private memo")[0], 0)
        code, result = self.feedback(rework, decision="needs_rework", correction_cycles=2)
        self.assertEqual(code, 0)
        self.assertIsNone(result["result"]["measurement"]["human_rework_duration"])
        _, aggregate = self.call("aggregate")
        totals = aggregate["result"]
        self.assertEqual(totals["recorded_attempts"], 3)
        self.assertEqual(totals["acceptance_rate"]["value"], 0.5)
        self.assertEqual(totals["rework_rate"]["value"], 0.5)
        self.assertIsNone(totals["workflow_completion_rate"]["value"])
        _, export = self.call("export", complete_observation_set=True)
        self.assertEqual(export["result"]["aggregate"]["workflow_completion_rate"]["value"], 1)
        data = json.dumps(export)
        for private in (accepted, rework, "Private memo", "timestamp_utc", "https://github.com/"):
            self.assertNotIn(private, data)
        self.assertEqual(len(export["result"]["observations"]), 3)

    def test_unknown_ineligible_and_duplicate_feedback(self):
        with patch(FETCH) as fetch:
            self.assertEqual(self.feedback(str(uuid4()))[1]["error"]["code"], "unknown_execution")
            self.assertEqual(self.feedback("../other")[1]["error"]["code"], "invalid_request")
            fetch.assert_not_called()
        blocked = self.record({"pr_url": GRANT["pr_url"]}, expected_code=2)
        self.assertEqual(self.feedback(blocked)[1]["error"]["code"], "ineligible_execution")
        identity = self.record()
        self.assertEqual(self.feedback(identity)[0], 0)
        self.assertEqual(self.feedback(identity, decision="needs_rework")[1]["error"]["code"], "duplicate_feedback")
        _, data = self.call("aggregate", complete_observation_set=True)
        self.assertEqual(data["result"]["workflow_completion_rate"]["value"], 0.5)

    def test_negative_invalid_and_unknown_observations(self):
        identity = self.record()
        for duration in (-1, True, 1.5):
            with self.subTest(duration=duration):
                code, _ = self.feedback(identity, review={"milliseconds": duration, "provenance": "human_reported"})
                self.assertEqual(code, 1)
        self.assertEqual(self.feedback(identity, correction_cycles=-1)[0], 1)
        self.assertEqual(self.feedback(identity, timestamp_utc="yesterday")[0], 1)
        code, reply = self.feedback(identity, rework=None, review=None)
        self.assertEqual(code, 0)
        self.assertFalse(reply["result"]["measurement"]["total_observed_task_time"]["complete"])

    def test_zero_denominator_and_corrupt_counts(self):
        _, response = self.call("aggregate", complete_observation_set=True)
        for key in ("workflow_completion_rate", "acceptance_rate", "rework_rate", "citation_verification_coverage"):
            metric = response["result"][key]
            self.assertEqual(metric["denominator"], 0)
            self.assertIsNone(metric["value"])
        identity = self.record()
        path = self.store / f"{identity}.run"
        record = json.loads(path.read_text())
        record["references_verified"] = record["references_checked"] + 1
        path.write_text(json.dumps(record))
        self.assertEqual(self.call("get", execution_id=identity)[1]["error"]["code"], "storage_failed")

    def test_partial_citation_coverage_cannot_be_accepted(self):
        def corrupt(*args):
            record = _build_record(*args)
            record["verified_facts"][-1]["sources"][-1]["excerpt"] = "+absent"
            return record

        with patch("server.scop_pr_summary._build_record", side_effect=corrupt):
            identity = self.record(expected_code=1)
        _, retrieved = self.call("get", execution_id=identity)
        coverage = retrieved["result"]["measurement"]["citation_verification_coverage"]
        self.assertEqual((coverage["numerator"], coverage["denominator"], coverage["value"]), (3, 4, 0.75))
        self.assertEqual(self.feedback(identity)[1]["error"]["code"], "ineligible_execution")

    def test_corrupt_timestamp_and_symlinked_record_fail_closed(self):
        identity = self.record()
        _, feedback = self.feedback(identity)
        data = feedback["result"]["feedback"]
        data["timestamp_utc"] = "2026-04-01T12:00:00-03:00"
        (self.store / f"{identity}.feedback").write_text(json.dumps(data))
        self.assertEqual(self.call("get", execution_id=identity)[1]["error"]["code"], "storage_failed")

        unknown = str(uuid4())
        (self.store / f"{unknown}.run").symlink_to(self.store / f"{identity}.run")
        self.assertEqual(self.call("get", execution_id=unknown)[1]["error"]["code"], "storage_failed")

    def test_denial_bad_input_and_unsafe_storage_do_no_work(self):
        with patch(FETCH) as fetch:
            code, reply = self.call("run", request=GRANT)
            self.assertEqual((code, reply["error"]["code"]), (2, "permission_denied"))
            code, _ = handle_request_bytes(b" " * (MAX_REQUEST_BYTES + 1), self.store)
            self.assertEqual(code, 1)
            with patch("server.scop_measurement.os.open", side_effect=OSError("private diagnostics")):
                code, reply = self.call("run", request=GRANT, permissions=[LOCAL_WRITE])
            self.assertEqual((code, reply["error"]["code"]), (1, "storage_failed"))
            self.assertNotIn("private diagnostics", str(reply))
            raw = json.dumps({"operation": "run", "request": GRANT, "permissions": [LOCAL_WRITE]}).encode()
            self.assertEqual(handle_request_bytes(raw, Path(__file__).parent)[1]["error"]["code"], "unsafe_store")
            self.assertEqual(list(self.store.iterdir()), [])
            with TemporaryDirectory(dir=Path("/tmp").resolve()) as outside:
                link = self.store / "link"
                link.symlink_to(outside, target_is_directory=True)
                self.assertEqual(handle_request_bytes(raw, link)[1]["error"]["code"], "storage_failed")
                self.assertEqual(list(Path(outside).iterdir()), [])
            fetch.assert_not_called()

    @skipUnless(os.environ.get("SCOP_LIVE_TESTS") == "1", "set SCOP_LIVE_TESTS=1 for public GitHub")
    def test_live_cli_persists_workspace_execution_and_retrieves_it(self):
        cmd = [sys.executable, "-B", "-m", "server.scop_measurement", "--store-dir", str(self.store)]
        run = subprocess.run(cmd, input=json.dumps({"operation": "run", "request": GRANT,
                                                    "permissions": [LOCAL_WRITE]}),
                             text=True, capture_output=True, timeout=50)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        execution = json.loads(run.stdout)["result"]["workspace"]["execution"]
        self.assertEqual(execution["references_verified"], 4)
        code, retrieval = self.call("get", execution_id=execution["execution_id"])
        self.assertEqual(code, 0)
        self.assertEqual(retrieval["result"]["execution"]["status"], "completed")
        self.assertIsNone(retrieval["result"]["feedback"])
