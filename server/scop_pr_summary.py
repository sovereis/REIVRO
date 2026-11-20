"""Generate and verify a deterministic summary of a public GitHub PR."""

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
import runpy
from time import monotonic

from .scop_github_evidence import (
    GITHUB_READ,
    LiveResult,
    _MAX_FILE_PAGES,
    _Mismatch,
    _NETWORK_BUDGET_SECONDS,
    _Unavailable,
    _VALIDATOR_PATH,
    _compare_sources,
    _fetch_files,
    _fetch_metadata,
)
from .scop_runtime import EvidenceReference, Status


_MAX_SAMPLES = 5
_MAX_EXCERPT = 400
_LIMITATIONS = (
    "Samples at most five changed files by line count and quotes representative lines.",
    "Uses the PR body as author-provided context. Motivation is reported only when explicitly labeled.",
    "Verifies citations against the fetched responses. Responses are collected sequentially, and claim interpretation remains a reviewer judgment.",
)


@dataclass
class SummaryResult(LiveResult):
    summary: dict | None = None
    limitations: tuple[str, ...] = _LIMITATIONS


def _sample(item: dict) -> list[str]:
    patch = item.get("patch")
    added, removed = item.get("additions"), item.get("deletions")
    if (not isinstance(patch, str) or type(added) is not int or type(removed) is not int
            or added < 0 or removed < 0):
        raise _Unavailable("GitHub omitted patch evidence or line counts")
    lines = patch.split("\n")
    if (sum(line.startswith("+") for line in lines) != added
            or sum(line.startswith("-") for line in lines) != removed
            or not lines[0].startswith("@@ ")):
        raise _Unavailable("A changed file has incomplete patch evidence")
    samples = {}
    for line in lines:
        if line.startswith(("+", "-")) and line[1:].strip() and len(line) <= _MAX_EXCERPT:
            samples.setdefault(line[0], line)
    return list(samples.values())


def _description_excerpt(body: str) -> tuple[str, bool] | None:
    labels = {"motivation", "why", "rationale"}
    context = None
    motivation_section = False
    fence = None
    visible = re.sub(r"<!--.*?(?:-->|$)", "\n", body, flags=re.S)
    for line in visible.splitlines():
        text = line.strip()
        if not text:
            continue
        if marker := re.match(r"`{3,}|~{3,}", text):
            kind = marker[0][0]
            if fence is None:
                fence = kind
            elif fence == kind:
                fence = None
            continue
        if fence is not None:
            continue
        if text.startswith("#"):
            motivation_section = text.lstrip("#").strip().lower() in labels
            continue
        label, separator, rest = text.partition(":")
        if separator and label.strip().lower() in labels:
            if rest.strip():
                return rest.strip()[:_MAX_EXCERPT], True
            motivation_section = True
        elif motivation_section:
            return text[:_MAX_EXCERPT], True
        elif context is None:
            context = text[:_MAX_EXCERPT]
    return (context, False) if context else None


def _build_record(url: str, metadata: dict, files: dict) -> dict:
    merged, body = metadata.get("merged"), metadata.get("body")
    if type(merged) is not bool or "body" not in metadata or (body is not None and not isinstance(body, str)):
        raise _Unavailable("GitHub omitted required PR metadata")
    facts = [{
        "claim": f"GitHub reports merged = {json.dumps(merged)}.",
        "sources": [{"kind": "metadata", "url": url, "locator": "merged", "excerpt": json.dumps(merged)}],
    }]
    if body and (description := _description_excerpt(body)):
        excerpt, motivation = description
        label = "Author-reported motivation excerpt" if motivation else "Author description excerpt"
        facts.append({
            "claim": f"{label}: {excerpt}",
            "sources": [{"kind": "description", "url": url, "locator": "body", "excerpt": excerpt}],
        })

    samples = [(name, item, _sample(item)) for name, item in files.items()]
    samples.sort(key=lambda entry: (-(entry[1]["additions"] + entry[1]["deletions"]), entry[0]))
    cited_files = 0
    for name, _, lines in samples:
        if not lines:
            continue
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        changes = "; ".join(
            f"{'adds' if line.startswith('+') else 'removes'} `{line[1:].strip()}`"
            for line in lines
        )
        facts.append({
            "claim": f"`{name}` {changes}.",
            "sources": [
                {"kind": "diff", "url": f"{url}/files#diff-{digest}", "locator": name, "excerpt": line}
                for line in lines
            ],
        })
        cited_files += 1
        if cited_files == _MAX_SAMPLES:
            break
    if not cited_files:
        raise _Unavailable("No representative changed lines are available")
    return {
        "pr_url": url,
        "checked_on": datetime.now(UTC).date().isoformat(),
        "status": "summarized",
        "verified_facts": facts,
        "assumptions": [],
        "limitations": [*_LIMITATIONS, f"Cites {cited_files} of {len(files)} changed files."],
        "blocked_reason": None,
    }


def summarize(pr_url: str, permissions: tuple[str, ...] = ()) -> SummaryResult:
    started = monotonic()
    outcome = SummaryResult()

    def event(status: Status, message: str) -> None:
        outcome.status = status
        outcome.duration_ms = round((monotonic() - started) * 1000, 3)
        outcome.events.append({"status": status, "elapsed_ms": outcome.duration_ms, "message": message})

    def stop(status: Status, code: str, message: str) -> SummaryResult:
        outcome.error_code, outcome.error_message = code, message
        event(status, message)
        return outcome

    event(Status.QUEUED, "PR summary requested")
    if permissions != (GITHUB_READ,):
        return stop(Status.BLOCKED, "permission_denied", "Explicit github:read-pr-evidence permission is required")
    try:
        schema = runpy.run_path(str(_VALIDATOR_PATH))
        identity = schema["PR_URL"].fullmatch(pr_url) if isinstance(pr_url, str) and len(pr_url) <= 300 else None
        if not identity or any(part in {".", ".."} for part in identity.groups()[:2]):
            return stop(Status.FAILED, "invalid_pr_url", "Expected a canonical public GitHub PR URL")
        outcome.pr_url = pr_url
        event(Status.RUNNING, "Fetching public GitHub evidence")
        deadline = monotonic() + _NETWORK_BUDGET_SECONDS
        endpoint, metadata = _fetch_metadata(pr_url, identity.groups(), deadline)
        changed_files = metadata.get("changed_files")
        if type(changed_files) is not int or not 0 < changed_files <= _MAX_FILE_PAGES * 100:
            raise _Unavailable("PR file count is missing, empty, or outside the fetch limit")
        files = _fetch_files(endpoint, deadline)
        if len(files) != changed_files:
            raise _Unavailable("GitHub returned an incomplete file list")
        record = _build_record(pr_url, metadata, files)
        _, sources = schema["validate"](record)
        outcome.offline_validation = "offline_structure"
        _compare_sources(metadata, files, sources, outcome)
        outcome.evidence_references = tuple(
            EvidenceReference(ref["kind"], ref["url"], ref["locator"]) for ref in sources
        )
        outcome.summary = record
    except KeyboardInterrupt:
        return stop(Status.CANCELLED, "interrupted", "PR summary generation interrupted")
    except _Unavailable as exc:
        return stop(Status.BLOCKED, "github_unavailable", str(exc))
    except _Mismatch:
        return stop(Status.FAILED, "evidence_mismatch", "A generated excerpt did not match the GitHub evidence")
    except (UnicodeError, ValueError):
        return stop(Status.FAILED, "invalid_record", "The generated record did not pass structural validation")
    except Exception:
        return stop(Status.FAILED, "summary_failed", "PR summary generation could not complete")
    event(Status.COMPLETED, "Generated summary passed schema and GitHub evidence checks")
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr_url", help="Canonical public GitHub pull request URL")
    parser.add_argument("--permission", action="append", default=[], help=f"Required opt-in: {GITHUB_READ}")
    args = parser.parse_args()
    result = summarize(args.pr_url, tuple(args.permission))
    print(json.dumps(asdict(result), indent=2))
    return {Status.COMPLETED: 0, Status.FAILED: 1, Status.BLOCKED: 2, Status.CANCELLED: 130}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
