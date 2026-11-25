"""Compare controller-verified functional observations without running source.

Observation objects are a trusted in-process boundary. A future adapter must
authenticate controller records out of band before constructing them. A guest
cannot establish provenance by setting fields in JSON, stdout or an exit code.
"""
from dataclasses import dataclass
import re

from .scop_firewall_memory import FirewallError, identifier, project_key

RULE = "functional-regression-v1"
_SHA = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_CASE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
EXECUTION_ERRORS = {"timeout", "unavailable", "isolation_failed"}


@dataclass(frozen=True)
class Plan:
    repository: str
    base: str
    head: str
    test_digest: str
    dependency_digest: str
    environment_digest: str
    tests: tuple[str, ...]


@dataclass(frozen=True)
class TestObservation:
    test_id: str
    status: str
    assertion_digest: str | None = None


@dataclass(frozen=True)
class Observation:
    execution_id: str
    revision: str
    test_digest: str
    dependency_digest: str
    environment_digest: str
    state: str
    tests: tuple[TestObservation, ...]
    evidence_digest: str


def _valid(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _result(status, reason, **evidence):
    return {"rule": RULE, "status": status, "reason": reason, **evidence}


def compare(plan: Plan, observations: tuple[Observation, ...] | None):
    """Require two fresh controller observations per revision and exact coverage."""
    if observations is None:
        return _result("ERROR", "runner_unavailable")
    if (type(plan) is not Plan or not isinstance(plan.tests, tuple)
            or not _valid(_SHA, plan.base) or not _valid(_SHA, plan.head) or plan.base == plan.head
            or not 0 < len(plan.tests) <= 128 or not all(_valid(_CASE, test) for test in plan.tests)
            or len(set(plan.tests)) != len(plan.tests)
            or not all(_valid(_DIGEST, digest) for digest in
                       (plan.test_digest, plan.dependency_digest, plan.environment_digest))):
        return _result("ERROR", "invalid_plan")
    try:
        repository = project_key(plan.repository)
    except (TypeError, FirewallError):
        return _result("ERROR", "invalid_repository")
    if not isinstance(observations, tuple) or len(observations) != 4 or any(type(run) is not Observation for run in observations):
        return _result("ERROR", "invalid_controller_record")
    if (not all(_valid(_CASE, run.execution_id) and _valid(_DIGEST, run.evidence_digest)
                for run in observations)
            or len({run.execution_id for run in observations}) != 4
            or len({run.evidence_digest for run in observations}) != 4
            or any(not isinstance(run.state, str) or not isinstance(run.revision, str)
                   or not isinstance(run.tests, tuple) for run in observations)):
        return _result("ERROR", "invalid_controller_record")
    if any(run.state in EXECUTION_ERRORS for run in observations):
        return _result("ERROR", "execution_failed")
    if any(run.state != "completed" for run in observations):
        return _result("ERROR", "invalid_controller_record")
    pinned = (plan.test_digest, plan.dependency_digest, plan.environment_digest)
    if any((run.test_digest, run.dependency_digest, run.environment_digest) != pinned
           for run in observations):
        return _result("INCONCLUSIVE", "trusted_inputs_changed")
    if any(run.revision not in {plan.base, plan.head} for run in observations):
        return _result("INCONCLUSIVE", "revision_mismatch")

    groups = {plan.base: [], plan.head: []}
    for run in observations:
        if (any(type(test) is not TestObservation or not _valid(_CASE, test.test_id) for test in run.tests)
                or len(run.tests) != len(plan.tests)
                or {test.test_id for test in run.tests} != set(plan.tests)):
            return _result("INCONCLUSIVE", "coverage_mismatch")
        for test in run.tests:
            if not ((test.status == "pass" and test.assertion_digest is None)
                    or (test.status == "assertion_failed" and _valid(_DIGEST, test.assertion_digest))):
                return _result("INCONCLUSIVE", "assertion_unverified")
        groups[run.revision].append({test.test_id: (test.status, test.assertion_digest) for test in run.tests})

    if any(len(group) != 2 for group in groups.values()):
        return _result("INCONCLUSIVE", "repetition_mismatch")
    if any(group[0] != group[1] for group in groups.values()):
        return _result("INCONCLUSIVE", "unstable_result")
    if any(status != "pass" for status, _ in groups[plan.base][0].values()):
        return _result("INCONCLUSIVE", "baseline_failed")

    trace = {
        "repository": repository, "base": plan.base, "head": plan.head,
        "test_digest": plan.test_digest, "dependency_digest": plan.dependency_digest,
        "environment_digest": plan.environment_digest, "tests": sorted(plan.tests),
        "runs": sorted(({"execution_id": run.execution_id, "revision": run.revision,
                         "evidence_digest": run.evidence_digest} for run in observations),
                       key=lambda run: run["execution_id"]),
        "assertions": [{"test_id": test, "assertion_digest": digest}
                       for test, (status, digest) in sorted(groups[plan.head][0].items())
                       if status == "assertion_failed"],
    }
    return _result("REGRESSION_DETECTED" if trace["assertions"] else "PASS", "stable_comparison",
                   trace=trace, evidence_id=identifier("functional", {"rule": RULE, **trace}))
