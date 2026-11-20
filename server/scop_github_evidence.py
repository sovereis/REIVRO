"""Opt-in, read-only GitHub verification of an existing PR-summary record.

This does not generate summaries or establish the semantic truth of a claim.
It checks that each cited excerpt appears in the current GitHub PR evidence.
"""
import argparse
from dataclasses import asdict, dataclass, field
from http.client import HTTPException
import io
import json
from pathlib import Path
import re
import runpy
import sys
from time import monotonic
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .scop_runtime import (
    MAX_RECORD_BYTES, READ_RECORD, EvidenceReference, Status, TaskRequest, run,
)

GITHUB_READ = "github:read-pr-evidence"
_MAX_RESPONSE_BYTES = 2_000_000
_MAX_FILE_PAGES = 3
_TIMEOUT_SECONDS = 10
_NETWORK_BUDGET_SECONDS = 30
_ENDPOINT = re.compile(
    r"https://api\.github\.com/repos/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+"
    r"/pulls/[1-9][0-9]*(?:/files\?per_page=100&page=[1-3])?"
)
_ROOT = Path(__file__).resolve().parents[1]
_VALIDATOR_PATH = _ROOT / "tests" / "pr-source-summary" / "validate.py"


@dataclass
class LiveResult:
    status: Status = Status.QUEUED
    validation_mode: str = "github_live_evidence"
    offline_validation: str | None = None
    pr_url: str | None = None
    references_checked: int = 0
    references_verified: int = 0
    evidence_references: tuple[EvidenceReference, ...] = ()
    duration_ms: float = 0.0
    events: list[dict] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    limitations: tuple[str, ...] = (
        "Checks cited excerpts against GitHub PR metadata, description and diff.",
        "Excerpt matching does not independently prove a claim's interpretation.",
        "Public GitHub PRs only; no authentication, writes or summary generation.",
    )


class _Unavailable(Exception):
    """The upstream resource or coverage was unavailable."""


class _Mismatch(Exception):
    """A citation is contradicted by fetched evidence."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _remaining(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise _Unavailable("GitHub evidence exceeded the network time budget")
    return remaining


def fetch_json(url: str, deadline: float):
    """Fetch bounded JSON from a fixed GitHub API endpoint."""
    if not _ENDPOINT.fullmatch(url):
        raise _Unavailable("unsupported evidence endpoint")
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "SCOP-github-evidence-v0.3",
    }, method="GET")
    opener = build_opener(_NoRedirect)
    raw = bytearray()
    try:
        timeout = min(_TIMEOUT_SECONDS, _remaining(deadline))
        with opener.open(request, timeout=timeout) as response:
            while True:
                _remaining(deadline)
                chunk = response.read1(min(65_536, _MAX_RESPONSE_BYTES + 1 - len(raw)))
                _remaining(deadline)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > _MAX_RESPONSE_BYTES:
                    raise _Unavailable("GitHub response exceeds the evidence limit")
    except (OSError, HTTPException) as exc:
        raise _Unavailable("GitHub evidence could not be retrieved") from exc
    try:
        return json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise _Unavailable("GitHub returned invalid evidence data") from exc


def _fetch_metadata(pr_url: str, identity: tuple[str, str, str], deadline: float):
    owner, repository, number = identity
    endpoint = f"https://api.github.com/repos/{owner}/{repository}/pulls/{number}"
    metadata = fetch_json(endpoint, deadline)
    if not isinstance(metadata, dict) or metadata.get("html_url") != pr_url:
        raise _Unavailable("GitHub returned an unexpected PR identity")
    return endpoint, metadata


def _fetch_files(endpoint: str, deadline: float, paths: set[str] | None = None) -> dict:
    files = {}
    for page in range(1, _MAX_FILE_PAGES + 1):
        data = fetch_json(f"{endpoint}/files?per_page=100&page={page}", deadline)
        if not isinstance(data, list) or len(data) > 100:
            raise _Unavailable("GitHub returned an unexpected file list")
        for item in data:
            filename = item.get("filename") if isinstance(item, dict) else None
            if not isinstance(filename, str):
                raise _Unavailable("GitHub returned an unexpected file entry")
            if filename in files:
                raise _Unavailable("GitHub returned a duplicate file entry")
            files[filename] = item
        if (paths is not None and paths <= files.keys()) or len(data) < 100:
            break
    if paths is not None and not paths <= files.keys():
        raise _Unavailable("Not all cited files were available within the fetch limit")
    return files


def _check_sources(record: dict, identity: tuple[str, str, str], sources: list[dict],
                   outcome: LiveResult) -> None:
    deadline = monotonic() + _NETWORK_BUDGET_SECONDS
    endpoint, metadata = _fetch_metadata(record["pr_url"], identity, deadline)
    paths = {s["locator"] for s in sources if s["kind"] == "diff"}
    files = _fetch_files(endpoint, deadline, paths) if paths else {}
    _compare_sources(metadata, files, sources, outcome)


def _compare_sources(metadata: dict, files: dict, sources: list[dict],
                     outcome: LiveResult) -> None:
    # Reuse the trusted existing hunk-matching implementation, without changing it.
    diff_match = runpy.run_path(str(_VALIDATOR_PATH))["diff_excerpt_matches"]
    for citation in sources:
        kind = citation["kind"]
        locator = citation["locator"]
        excerpt = citation["excerpt"]
        if kind == "diff":
            patch = files.get(locator, {}).get("patch")
            if not isinstance(patch, str):
                raise _Unavailable("A cited diff patch was unavailable")
            correct = diff_match(patch, excerpt)
        elif kind == "metadata":
            value = metadata.get(locator)
            if isinstance(value, (bool, int, float)):
                value = json.dumps(value)
            correct = value == excerpt
        elif kind == "description":
            body = metadata.get("body")
            correct = isinstance(body, str) and excerpt in body
        else:
            raise _Mismatch("Unsupported citation type")
        outcome.references_checked += 1
        if not correct:
            raise _Mismatch("A citation does not match the GitHub evidence")
        outcome.references_verified += 1


def run_live(task: str, source, permissions: tuple[str, ...] = ()) -> LiveResult:
    """Only fetch GitHub data after explicit opt-in and successful offline audit."""
    started = monotonic()
    outcome = LiveResult()

    def event(status: Status, message: str):
        outcome.status = status
        outcome.duration_ms = round((monotonic() - started) * 1000, 3)
        outcome.events.append({"status": status, "elapsed_ms": outcome.duration_ms, "message": message})

    def stop(status: Status, code: str, message: str):
        outcome.error_code, outcome.error_message = code, message
        event(status, message)
        return outcome

    event(Status.QUEUED, "Evidence verification requested")
    if tuple(permissions) != (GITHUB_READ,):
        return stop(Status.BLOCKED, "permission_denied",
                    "Explicit github:read-pr-evidence permission is required")
    try:
        raw = source.read(MAX_RECORD_BYTES + 1)
        # Delegate all record format and selection checks to the existing runtime.
        offline = run(TaskRequest(task, (READ_RECORD,)), io.BytesIO(raw))
        outcome.offline_validation = offline.validation_mode
        if offline.status is not Status.COMPLETED:
            return stop(offline.status, offline.error.code if offline.error else "offline_failed",
                        "Offline record validation did not complete")
        outcome.pr_url = offline.audit.pr_url
        outcome.evidence_references = offline.evidence_references
        event(Status.RUNNING, "Offline structure passed; checking GitHub evidence")
        record = json.loads(raw)
        identity = runpy.run_path(str(_VALIDATOR_PATH))["PR_URL"].fullmatch(outcome.pr_url).groups()
        # The offline validator already checked the canonical PR URL and citations.
        sources = [citation for fact in record["verified_facts"] for citation in fact["sources"]]
        _check_sources(record, identity, sources, outcome)
    except KeyboardInterrupt:
        return stop(Status.CANCELLED, "interrupted", "Evidence verification interrupted")
    except _Unavailable:
        return stop(Status.BLOCKED, "github_unavailable",
                    "GitHub evidence is unavailable or exceeds the configured bounds")
    except _Mismatch:
        return stop(Status.FAILED, "evidence_mismatch",
                    "One or more cited excerpts did not match GitHub")
    except Exception:
        return stop(Status.FAILED, "verification_failed",
                    "Evidence verification could not complete")
    event(Status.COMPLETED, "All cited excerpts were found in live GitHub evidence")
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task description for SCOP skill selection")
    parser.add_argument("--permission", action="append", default=[],
                        help=f"Required opt-in: {GITHUB_READ}")
    args = parser.parse_args()
    result = run_live(args.task, sys.stdin.buffer, tuple(args.permission))
    print(json.dumps(asdict(result), indent=2))
    return {Status.COMPLETED: 0, Status.FAILED: 1,
            Status.BLOCKED: 2, Status.CANCELLED: 130}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
