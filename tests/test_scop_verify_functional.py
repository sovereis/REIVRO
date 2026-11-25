from dataclasses import replace
import json

import pytest

from benchmarks.functional.run import MANIFEST, PLAN, benchmark, samples
from server.scop_verify_functional import compare


@pytest.mark.parametrize("case", json.loads(MANIFEST.read_text())["cases"], ids=lambda case: case["id"])
def test_fixed_functional_contract(case):
    result = compare(PLAN, samples(case))
    assert result["status"] == case["expected"]
    if result["status"] in {"PASS", "REGRESSION_DETECTED"}:
        assert result["trace"]["tests"] == list(PLAN.tests)
        assert len(result["trace"]["runs"]) == 4
        assert compare(PLAN, tuple(reversed(samples(case)))) == result
    else:
        assert "evidence_id" not in result


def test_invalid_plan_and_repetitions_fail_closed():
    case = {"base": ["pass", "pass"], "head": ["pass", "pass"]}
    assert compare(replace(PLAN, head=PLAN.base), samples(case))["status"] == "ERROR"
    assert compare(PLAN, samples(case)[:-1])["status"] == "ERROR"
    assert compare(PLAN, tuple(replace(run, revision=PLAN.base) for run in samples(case)))["status"] == "INCONCLUSIVE"


def test_benchmark_reports_all_scenarios_without_execution():
    report = benchmark()
    assert report["matched"] == len(report["results"]) == 17
    assert {row["status"] for row in report["results"]} == {
        "PASS", "REGRESSION_DETECTED", "INCONCLUSIVE", "ERROR",
    }
    assert report["runtime_executions"] == 0 and not report["firewall_enforced"]
