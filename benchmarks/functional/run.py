"""Run fixture comparisons without executing source or contacting a provider."""
import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from server.scop_verify_functional import Observation, Plan, TestObservation, compare

MANIFEST = Path(__file__).with_name("scenarios-v1.json")
PLAN = Plan("example/fixture", "a" * 40, "b" * 40, "1" * 64, "2" * 64, "3" * 64, ("suite.case",))


def samples(case):
    fault = case.get("fault")
    if fault == "unavailable":
        return None
    runs = []
    for side, revision in (("base", PLAN.base), ("head", PLAN.head)):
        for index, status in enumerate(case[side]):
            run_id = f"{side}-{index}"
            state = "timeout" if status == "timeout" else "completed"
            assertion = "4" * 64 if status == "assertion_failed" else None
            tests = (TestObservation(PLAN.tests[0], status, assertion),)
            runs.append(Observation(run_id, revision, PLAN.test_digest, PLAN.dependency_digest,
                                    PLAN.environment_digest, state, tests, sha256(run_id.encode()).hexdigest()))
    if fault == "guest":
        runs[-1] = {"state": "completed", "stdout": "PASS", "exit_code": 0}
    elif fault == "assertion":
        runs[-1] = replace(runs[-1], tests=(replace(runs[-1].tests[0], assertion_digest="9" * 64),))
    elif fault == "unverified_assertion":
        runs[-1] = replace(runs[-1], tests=(replace(runs[-1].tests[0], assertion_digest=None),))
    elif fault == "coverage":
        runs[-1] = replace(runs[-1], tests=())
    elif fault:
        runs[-1] = replace(runs[-1], **{fault: runs[0].execution_id if fault == "execution_id"
                                        else "c" * 40 if fault == "revision" else "9" * 64})
    return tuple(runs)


def benchmark():
    raw = MANIFEST.read_bytes()
    manifest = json.loads(raw)
    rows = [{"id": case["id"], "expected": case["expected"], **compare(PLAN, samples(case))}
            for case in manifest["cases"]]
    return {"manifest_sha256": sha256(raw).hexdigest(), "version": manifest["version"],
            "source": manifest["source"], "runtime_executions": 0, "firewall_enforced": False,
            "matched": sum(row["status"] == row["expected"] for row in rows), "results": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    report = benchmark()
    report["code_sha"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=MANIFEST.parents[2], text=True,
    ).strip()
    options.output.write_text(json.dumps(report, indent=2) + "\n")
    return int(report["matched"] != len(report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
