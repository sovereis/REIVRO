"""Opt-in, single-delivery GitHub Checks worker for the staging firewall."""
import argparse
import base64
from dataclasses import dataclass
from hashlib import sha256, sha1
import hmac
from http.client import HTTPException
import json
import os
import re
import sys
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener
from uuid import UUID

from .scop_firewall import VERIFIER_VERSION
from .scop_firewall_memory import FirewallError, project_key
from .scop_github_evidence import GITHUB_READ, _NoRedirect
from .scop_verify_syntax import RULE, verify_syntax

ARTIFACT = ".reivro/protections/python-syntax-regression.json"
MAX_WEBHOOK = 512 * 1024
_SHA = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_STAGING_REF = re.compile(r"[a-z0-9]{20}")
_KNOWN_PRODUCTION = "hnlmnswotenppgdqxvkv"
_CONCLUSION = {
    "VIOLATION": "failure", "PASS": "success", "INCONCLUSIVE": "neutral",
    "ERROR": "action_required", "INACTIVE": "neutral", "OBSERVED": "neutral",
}
_SUMMARY = {
    "VIOLATION": "A Python syntax regression was detected under the approved protection.",
    "PASS": "No Python syntax regression was found within the approved scope.",
    "INCONCLUSIVE": "Evidence or the trusted protection artifact was incomplete.",
    "ERROR": "The verifier could not complete the check.",
    "INACTIVE": "The protection is inactive or the revision matches the original failure.",
    "OBSERVED": "Evidence was collected for review. No approved protection was in effect.",
}


class CheckError(Exception):
    """Reject a delivery or signal an unavailable trusted dependency."""


class ProviderHTTPError(CheckError):
    def __init__(self, status):
        super().__init__(f"Provider rejected the request (HTTP {status})")
        self.status = status


class ArtifactUnavailable(CheckError):
    """The trusted artifact is absent or does not constitute valid evidence."""


def _canonical_uuid(value):
    try:
        result = str(UUID(value))
    except (AttributeError, ValueError, TypeError) as exc:
        raise CheckError("Invalid UUID") from exc
    if result != value:
        raise CheckError("Noncanonical UUID")
    return result


def _sha(value, pattern=_SHA):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise CheckError("Invalid revision or digest")
    return value


def _id(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise CheckError("Invalid GitHub identity")
    return value


def _decode_object(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise CheckError("Duplicate JSON key")
            result[key] = value
        return result

    result = json.loads(body, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise CheckError("Expected a JSON object")
    return result


def _request(method, url, headers, payload=None, limit=524288, allow_null=False):
    body = None if payload is None else json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()
    if body is not None and len(body) > limit:
        raise CheckError("Request exceeds limit")
    deadline = monotonic() + 10
    request = Request(url, data=body, headers={"Content-Type": "application/json", **headers}, method=method)
    try:
        with build_opener(_NoRedirect).open(request, timeout=5) as response:
            raw = bytearray()
            while True:
                chunk = response.read1(min(65536, limit + 1 - len(raw)))
                if monotonic() > deadline:
                    raise CheckError("Provider response exceeded time budget")
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > limit:
                    raise CheckError("Provider response exceeds limit")
            if allow_null and raw.strip() == b"null":
                return None
            return _decode_object(raw)
    except HTTPError as exc:
        with exc:
            raise ProviderHTTPError(exc.code) from None
    except (OSError, HTTPException, ValueError, RecursionError):
        raise CheckError("Provider response unavailable or invalid") from None


@dataclass(frozen=True)
class Project:
    repository: str
    repository_id: int
    installation_id: int
    base_ref: str

    def __post_init__(self):
        if project_key(self.repository) != self.repository:
            raise CheckError("Configured repository must be lowercase")
        _id(self.repository_id)
        _id(self.installation_id)
        if not self.base_ref or len(self.base_ref) > 200:
            raise CheckError("Invalid trusted base branch")


@dataclass(frozen=True)
class Revision:
    pr: int
    base_sha: str
    head_sha: str


def _revision(pr_data, project):
    base = pr_data["base"]
    if (_id(base["repo"]["id"]) != project.repository_id
            or base["repo"]["full_name"].lower() != project.repository
            or base["ref"] != project.base_ref or base["repo"]["private"] is not False):
        raise CheckError("Repository or base branch outside the configured scope")
    number = _id(pr_data["number"])
    if number >= 2**31:
        raise CheckError("PR number outside the supported range")
    return Revision(number, _sha(base["sha"]), _sha(pr_data["head"]["sha"]))


def authenticate(body, signature, delivery, event, secret, project):
    if len(secret) < 32 or not 0 < len(body) <= MAX_WEBHOOK or event != "pull_request":
        raise CheckError("Unsupported webhook")
    expected = "sha256=" + hmac.digest(secret, body, "sha256").hex()
    if (not isinstance(signature, str) or not signature.isascii()
            or not hmac.compare_digest(signature, expected)):
        raise CheckError("Webhook signature could not be verified")
    key = _canonical_uuid(delivery)
    try:
        payload = _decode_object(body)
        if payload["action"] not in ("opened", "synchronize", "reopened"):
            raise CheckError("Unsupported pull request action")
        if (_id(payload["installation"]["id"]) != project.installation_id
                or _id(payload["repository"]["id"]) != project.repository_id
                or payload["repository"]["full_name"].lower() != project.repository
                or payload["repository"]["private"] is not False):
            raise CheckError("Unexpected installation or repository")
        revision = _revision(payload["pull_request"], project)
        if _id(payload["number"]) != revision.pr:
            raise CheckError("Inconsistent pull request number")
        return key, revision
    except (KeyError, AttributeError, TypeError, ValueError, RecursionError):
        raise CheckError("Invalid webhook payload") from None


class StagingMemory:
    """PostgREST verifies the JWT. DB operations authorize its subject by project."""

    def __init__(self, ref, publishable_key, access_token):
        if not _STAGING_REF.fullmatch(ref) or ref == _KNOWN_PRODUCTION:
            raise CheckError("Expected an isolated staging ref, distinct from production")
        if not publishable_key.startswith("sb_publishable_") or not access_token:
            raise CheckError("A publishable key and a scoped Auth user JWT are required")
        self.url = f"https://{ref}.supabase.co/rest/v1/rpc"
        self.headers = {"apikey": publishable_key, "Authorization": "Bearer " + access_token,
                        "Content-Profile": "reivro_checks_api"}

    def dispatch(self, action, request):
        return _request("POST", self.url + "/dispatch", self.headers, {"action": action, "request": request})

    def read_run(self, repository_id, run_id):
        return _request("POST", self.url + "/read_run", self.headers,
                        {"p_repository_id": _id(repository_id), "p_run_id": _canonical_uuid(run_id)},
                        allow_null=True)


class GitHubEvidence:
    """Use an externally issued installation token. It is never sent to the compiler."""

    def __init__(self, token, project):
        if not token:
            raise CheckError("A repository-scoped installation token is required")
        self.url = "https://api.github.com/repos/" + project.repository
        self.headers = {
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "REIVRO-staging",
        }

    def pull(self, number):
        return _request("GET", f"{self.url}/pulls/{_id(number)}", self.headers)

    def artifact(self, base_sha):
        try:
            result = _request("GET", f"{self.url}/contents/{quote(ARTIFACT)}?ref={_sha(base_sha)}",
                              self.headers, limit=24576)
        except ProviderHTTPError as exc:
            if exc.status == 404:
                raise ArtifactUnavailable("Approved artifact unavailable at trusted base") from None
            raise
        if (result.get("type") != "file" or result.get("path") != ARTIFACT
                or result.get("encoding") != "base64" or type(result.get("size")) is not int
                or not 0 < result["size"] <= 8192 or not isinstance(result.get("content"), str)):
            raise ArtifactUnavailable("Trusted protection artifact is unavailable")
        try:
            raw = base64.b64decode(result["content"].replace("\n", ""), validate=True)
        except ValueError as exc:
            raise ArtifactUnavailable("Invalid protection artifact encoding") from exc
        git_blob = sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()
        if len(raw) != result["size"] or git_blob != result.get("sha"):
            raise ArtifactUnavailable("Trusted protection artifact failed blob integrity")
        return raw


class GitHub(GitHubEvidence):
    """Legacy CLI client with Check publication authority."""

    def publish(self, check):
        return _request("POST", self.url + "/check-runs", self.headers, check, limit=65536)


def _same_revision(github, project, revision):
    try:
        pr = github.pull(revision.pr)
        return pr["state"] == "open" and _revision(pr, project) == revision
    except (KeyError, TypeError, AttributeError) as exc:
        raise CheckError("Malformed live GitHub PR metadata") from exc


def _error_report(status, reason):
    return {"rule": RULE, "status": status, "reason": reason, "files": []}


def _inspect(project, revision, claim, github, executor=None):
    actual = None
    protection_state = "not_configured"
    if claim.get("protection_id") is not None:
        protection_state = "unchecked"
        try:
            expected = _sha(claim.get("artifact_digest"), _DIGEST)
            candidate = sha256(github.artifact(revision.base_sha)).hexdigest()
            if hmac.compare_digest(candidate, expected):
                actual, protection_state = candidate, "verified"
            else:
                protection_state = "artifact_mismatch"
        except ArtifactUnavailable:
            protection_state = "artifact_unavailable"
        except CheckError:
            protection_state = "provider_error"

    meta = github.pull(revision.pr)
    if _revision(meta, project) != revision or meta.get("state") != "open":
        return {**_error_report("INCONCLUSIVE", "PR moved before verification"),
                "protection_state": protection_state}, None
    # Use GitHub's canonical case while maintaining an exact, fixed origin and repository.
    name = meta["base"]["repo"]["full_name"]
    if project_key(name) != project.repository:
        raise CheckError("Inconsistent canonical repository")
    url = f"https://github.com/{name}/pull/{revision.pr}"
    options = {} if executor is None else {"executor": executor}
    report = verify_syntax(url, (GITHUB_READ,), **options)
    if report["status"] in {"PASS", "REGRESSION_DETECTED"} and (
        report.get("head_sha") != revision.head_sha or report.get("base_sha") != revision.base_sha
        or report.get("pr_url") != url or str(report.get("repository")).lower() != project.repository
        or report.get("pr") != revision.pr or report.get("rule") != RULE
    ):
        return {**_error_report("INCONCLUSIVE", "Verifier returned a different revision"),
                "protection_state": protection_state}, None
    report = {**report, "verification_status": report["status"], "protection_state": protection_state}
    if protection_state == "provider_error" and report["status"] != "REGRESSION_DETECTED":
        report["status"] = "ERROR"
    elif protection_state in {"artifact_unavailable", "artifact_mismatch"} and report["status"] == "ERROR":
        report["status"] = "INCONCLUSIVE"
    return report, actual


def analyze(body, signature, delivery, event, *, project, secret, memory, github, executor=None,
            durable=False):
    key, revision = authenticate(body, signature, delivery, event, secret, project)
    if not durable and not _same_revision(github, project, revision):
        return {"status": "STALE"}
    scope = {"repository_id": project.repository_id, "installation_id": project.installation_id}
    claim = memory.dispatch("claim_durable" if durable else "claim", {
        **scope, "repository": project.repository, "base_ref": project.base_ref, "delivery": key,
        "pr": revision.pr, "base_sha": revision.base_sha, "head_sha": revision.head_sha,
    })
    if not durable and claim.get("duplicate") is True:
        return {"status": "DUPLICATE"}
    run = _canonical_uuid(claim.get("run_id"))
    ownership = {**scope, "run_id": run}
    if durable:
        state = claim.get("state")
        if state in {"completed", "terminal", "busy"}:
            return {"status": state.upper(), "run_id": run}
        fence = claim.get("fence")
        if state != "running" or type(fence) is not int or not 1 <= fence <= 3:
            raise CheckError("Invalid execution claim")
        ownership.update(attempt_id=_canonical_uuid(claim.get("attempt_id")), fence=fence)
    try:
        if durable and not _same_revision(github, project, revision):
            report, digest = _error_report("INCONCLUSIVE", "PR revision is no longer current"), None
        else:
            if durable:
                renewed = memory.dispatch("renew_durable", ownership)
                if renewed != {"state": "running", "run_id": run}:
                    raise CheckError("Execution lease renewal not confirmed")
            report, digest = _inspect(project, revision, claim, github, executor)
            if not _same_revision(github, project, revision):
                report, digest = _error_report("INCONCLUSIVE", "PR moved during verification"), None
    except (CheckError, KeyError, TypeError, AttributeError):
        report, digest = _error_report("ERROR", "Evidence or provider unavailable"), None
    dimensions = {
        "verification_status": report.get("verification_status", report["status"]),
        "protection_state": report.get("protection_state", "unchecked"),
    }
    if durable and report["status"] == "ERROR":
        result = memory.dispatch("fail_durable", ownership)
        if result.get("run_id") != run or result.get("state") not in {"retryable", "terminal"}:
            raise CheckError("Execution failure transition not confirmed")
        return {"status": result["state"].upper(), "run_id": run,
                **dimensions, "security_decision": "review_required"}
    report["verifier_version"] = VERIFIER_VERSION
    result = memory.dispatch("finish_durable" if durable else "finish", {
        **ownership, "report": report, "artifact_digest": digest,
    })
    if durable and result.get("state") != "completed":
        raise CheckError("Execution completion not confirmed")
    outcome = result.get("outcome")
    if result.get("run_id") != run or outcome not in _CONCLUSION:
        raise CheckError("Unexpected result from staging memory")
    if outcome in {"PASS", "VIOLATION"} and (
        claim.get("protection_id") is None or digest is None or
        report["status"] != {"PASS": "PASS", "VIOLATION": "REGRESSION_DETECTED"}[outcome]
    ):
        raise CheckError("Staging outcome does not match verified evidence")
    if outcome == "INACTIVE":
        dimensions["protection_state"] = "inactive"
    decision = {"PASS": "allow", "VIOLATION": "block", "OBSERVED": "not_enforced",
                "INACTIVE": "not_enforced"}.get(outcome, "review_required")
    return {"status": outcome, "run_id": run, "head_sha": revision.head_sha,
            **dimensions, "security_decision": decision}


def publish_result(result, publisher):
    """Send a single Check. An ambiguous acknowledgement always requires review."""
    outcome = result["status"]
    run = _canonical_uuid(result["run_id"])
    head = _sha(result["head_sha"])
    conclusion = ("action_required" if result.get("security_decision") == "review_required"
                  else _CONCLUSION[outcome])
    try:
        check = publisher.publish({
            "name": "REIVRO Firewall (staging)", "head_sha": head,
            "external_id": run, "status": "completed", "conclusion": conclusion,
            "output": {"title": outcome, "summary": _SUMMARY[outcome] + f" Audit run: `{run}`."},
        })
        if (check.get("head_sha") != head or check.get("external_id") != run
                or check.get("status") != "completed" or check.get("conclusion") != conclusion):
            raise CheckError("Check response does not match requested publication")
        return {**result, "status": outcome, "run_id": run, "head_sha": head,
                "check_id": _id(check["id"])}
    except (CheckError, KeyError, TypeError):
        # Delivery remains consumed. A timed-out POST may already have succeeded.
        return {"status": "PUBLICATION_UNCERTAIN", "run_id": run,
                "head_sha": head, "outcome": outcome, "conclusion": conclusion}


def reconcile_publication(result, app_id, candidates):
    """Confirm one exact Check from a complete read-only lookup, or hold for review."""
    if result["status"] != "PUBLICATION_UNCERTAIN":
        raise CheckError("Expected uncertain Check publication")
    app_id = _id(app_id)
    run = _canonical_uuid(result["run_id"])
    head = _sha(result["head_sha"])
    matches = [check for check in candidates if check.get("external_id") == run]
    if len(matches) == 1:
        check = matches[0]
        if (check.get("app", {}).get("id") == app_id
                and check.get("name") == "REIVRO Firewall (staging)"
                and check.get("head_sha") == head and check.get("status") == "completed"
                and check.get("conclusion") == result.get("conclusion", _CONCLUSION[result["outcome"]])):
            return {"status": "CONFIRMED", "check_id": _id(check.get("id")), "run_id": run}
    return {"status": "REVIEW_REQUIRED", "run_id": run}


def handle(body, signature, delivery, event, *, project, secret, memory, github, publish=True):
    result = analyze(body, signature, delivery, event, project=project, secret=secret,
                     memory=memory, github=github)
    if publish and "run_id" in result:
        return publish_result(result, github)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish-staging-check", required=True, action="store_true")
    parser.parse_args()
    try:
        project = Project(os.environ["REIVRO_REPOSITORY"],
                          int(os.environ["REIVRO_REPOSITORY_ID"]),
                          int(os.environ["REIVRO_INSTALLATION_ID"]), os.environ["REIVRO_TRUSTED_BASE"])
        memory = StagingMemory(os.environ["REIVRO_STAGING_REF"], os.environ["REIVRO_PUBLISHABLE_KEY"],
                               os.environ["REIVRO_WORKER_JWT"])
        github = GitHub(os.environ["REIVRO_GITHUB_INSTALLATION_TOKEN"], project)
        result = handle(
            sys.stdin.buffer.read(MAX_WEBHOOK + 1), os.environ["REIVRO_WEBHOOK_SIGNATURE"],
            os.environ["REIVRO_WEBHOOK_DELIVERY"], os.environ["REIVRO_WEBHOOK_EVENT"],
            project=project, secret=os.environ["REIVRO_WEBHOOK_SECRET"].encode(),
            memory=memory, github=github,
        )
        print(json.dumps(result))
        return 1 if result["status"] in {"ERROR", "PUBLICATION_UNCERTAIN"} else 0
    except (CheckError, FirewallError, KeyError, ValueError):
        print(json.dumps({"status": "ERROR", "reason": "Staging delivery rejected or unavailable"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
