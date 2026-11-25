"""Normalize reusable task policies for the existing Rework Firewall."""
from hashlib import sha256

from .scop_firewall_memory import FirewallError, identifier

CATEGORY = "task-policy"
VERSION = "task-policy-v1"


def path_digest(path):
    return sha256(path if isinstance(path, bytes) else path.encode()).hexdigest()


def from_failure(contract, report, criterion_index=None, violation_index=None):
    """Select exactly one independently observed, reusable failure."""
    if (criterion_index is None) == (violation_index is None):
        raise FirewallError("Select exactly one failed observation")
    if criterion_index is not None:
        observations = report.get("criteria", ())
        if not 0 <= criterion_index < len(observations) or observations[criterion_index]["outcome"] != "unmet":
            raise FirewallError("Expected an unmet observed criterion")
        criterion = contract["criteria"][criterion_index]
        if criterion["kind"] not in {"exists", "blob_sha256"}:
            raise FirewallError("The criterion is task-specific")
        return criterion.copy(), [path_digest(criterion["path"])]
    violations = report.get("violations", ())
    if not 0 <= violation_index < len(violations):
        raise FirewallError("Expected an observed path violation")
    violation = violations[violation_index]
    digest = violation["path_sha256"]
    if violation["reason"] == "protected_path":
        path, = (path for path in contract["protected_paths"] if path_digest(path) == digest)
        return {"kind": "protected_path", "path": path}, [digest]
    if violation["reason"] != "out_of_scope":
        raise FirewallError("Unsupported path violation")
    return {"kind": "allowed_paths", "paths": sorted(contract["allowed_paths"])}, [digest]


def conflicts(policy, contract):
    kind, path = policy["kind"], policy.get("path")
    return any(
        (kind == "blob_sha256" and criterion["kind"] == kind and criterion.get("path") == path
         and criterion.get("digest") != policy["digest"])
        or (criterion["kind"] == "changed" and (
            kind == "protected_path" and criterion.get("path") == path
            or kind == "allowed_paths" and criterion.get("path") not in policy["paths"]))
        for criterion in contract["criteria"]
    )


def evaluate(policy, git, head, changed):
    """Return fingerprints of concrete violations of the same approved predicate."""
    kind = policy["kind"]
    if kind == "allowed_paths":
        return [path_digest(path) for path in sorted(changed - {path.encode() for path in policy["paths"]})]
    path = policy["path"]
    if kind == "protected_path":
        violated = path.encode() in changed
    elif kind == "blob_sha256":
        violated = git.blob(head, path, digest=True) != policy["digest"]
    elif kind == "exists":
        violated = git.blob(head, path) is not True
    else:
        raise FirewallError("Unsupported policy")
    return [path_digest(path)] if violated else []


def failure_key(repository, policy, fingerprint):
    return identifier("task-failure", [repository, VERSION, policy, fingerprint])
