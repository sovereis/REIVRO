"""Check public GitHub PRs for whitespace errors in added Python lines."""
import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re
import runpy
from time import monotonic
from urllib.parse import quote

from .scop_github_evidence import (
    GITHUB_READ, _MAX_FILE_PAGES, _NETWORK_BUDGET_SECONDS, _Unavailable,
    _fetch_files, _fetch_metadata,
)
from .scop_pr_summary import _VALIDATOR_PATH, _parse_identity
from .scop_runtime import Status

RULE = "python-trailing-whitespace"
_MAX_FINDINGS = 100
_HUNK = re.compile(r"@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@(?: .*)?")
_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class Finding:
    rule: str
    file: str
    line: int
    commit: str
    diff_url: str
    commit_file_url: str
    excerpt: str
    excerpt_truncated: bool


@dataclass(frozen=True)
class Report:
    status: Status
    pr_url: str | None = None
    head_sha: str | None = None
    base_sha: str | None = None
    python_files_checked: int = 0
    added_lines_checked: int = 0
    finding_count: int | None = None
    findings: tuple[Finding, ...] = ()
    error: str | None = None
    rule: str = RULE


def _revision(metadata):
    head, base = metadata.get("head"), metadata.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise _Unavailable("Missing GitHub revision metadata")
    revisions = head.get("sha"), base.get("sha")
    if not all(isinstance(value, str) and _SHA.fullmatch(value) for value in revisions):
        raise _Unavailable("Invalid GitHub revision metadata")
    return *revisions, metadata.get("changed_files")


def _added_lines(item):
    """Yield head-side line numbers only from complete unified diff hunks."""
    patch = item.get("patch")
    added, deleted = item.get("additions"), item.get("deletions")
    if any(type(count) is not int or count < 0 for count in (added, deleted)):
        raise _Unavailable("Invalid patch line totals")
    if not isinstance(patch, str) or not patch:
        if added == deleted == 0 and item.get("status") in {"renamed", "removed"}:
            return
        raise _Unavailable("A Python patch is unavailable")

    old_left = new_left = new_line = seen_added = seen_deleted = 0
    in_hunk = False
    for row in patch.removesuffix("\n").split("\n"):
        header = _HUNK.fullmatch(row)
        if header:
            if old_left or new_left:
                raise _Unavailable("Incomplete Python diff hunk")
            _, old_count, new_start, new_count = header.groups()
            old_left = int(old_count or "1")
            new_left = int(new_count or "1")
            new_line = int(new_start)
            in_hunk = True
            continue
        if not in_hunk:
            raise _Unavailable("Python patch is missing its hunk header")
        if row == r"\ No newline at end of file":
            continue
        prefix = row[:1]
        if prefix in {"+", " "} and new_line < 1:
            raise _Unavailable("Invalid Python diff line number")
        if prefix == "+":
            seen_added += 1
            yield new_line, row
        elif prefix == "-":
            seen_deleted += 1
        elif prefix != " ":
            raise _Unavailable("Invalid Python patch line")
        if prefix in {"-", " "}:
            old_left -= 1
        if prefix in {"+", " "}:
            new_left -= 1
            new_line += 1
        if old_left < 0 or new_left < 0:
            raise _Unavailable("Python diff hunk exceeds its declared length")
    if not in_hunk or old_left or new_left or (seen_added, seen_deleted) != (added, deleted):
        raise _Unavailable("Python patch is incomplete")


def verify(pr_url: str, permissions: tuple[str, ...] = ()) -> Report:
    if permissions != (GITHUB_READ,):
        return Report(Status.BLOCKED, error="Explicit github:read-pr-evidence permission is required")
    try:
        identity = _parse_identity(pr_url, runpy.run_path(str(_VALIDATOR_PATH)))
        if identity is None:
            return Report(Status.FAILED, error="Expected a canonical public GitHub PR URL")
        deadline = monotonic() + _NETWORK_BUDGET_SECONDS
        endpoint, metadata = _fetch_metadata(pr_url, identity, deadline)
        head, base, count = _revision(metadata)
        if type(count) is not int or not 0 <= count <= _MAX_FILE_PAGES * 100:
            raise _Unavailable("PR file count is missing or exceeds the fetch limit")
        files = _fetch_files(endpoint, deadline)
        if len(files) != count:
            raise _Unavailable("GitHub returned an incomplete file list")

        findings = []
        file_count = line_count = finding_count = 0
        for path, item in sorted(files.items()):
            if not path.endswith(".py"):
                continue
            file_count += 1
            for line, row in _added_lines(item):
                line_count += 1
                if not row.removesuffix("\r").endswith((" ", "\t")):
                    continue
                finding_count += 1
                if len(findings) < _MAX_FINDINGS:
                    anchor = sha256(path.encode()).hexdigest()
                    owner, repo, _ = identity
                    findings.append(Finding(
                        RULE, path, line, head, f"{pr_url}/files#diff-{anchor}R{line}",
                        f"https://github.com/{owner}/{repo}/blob/{head}/{quote(path)}#L{line}",
                        row[-400:], len(row) > 400,
                    ))

        _, latest = _fetch_metadata(pr_url, identity, deadline)
        if _revision(latest) != (head, base, count):
            raise _Unavailable("The PR revision changed during verification; retry")
        return Report(Status.COMPLETED, pr_url, head, base, file_count, line_count,
                      finding_count, tuple(findings))
    except KeyboardInterrupt:
        return Report(Status.CANCELLED, error="Verification interrupted")
    except _Unavailable as exc:
        return Report(Status.BLOCKED, pr_url, error=str(exc))
    except Exception:
        return Report(Status.FAILED, error="Verification could not complete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr_url", help="Canonical public GitHub PR URL")
    parser.add_argument("--permission", action="append", default=[], help=f"Required opt-in: {GITHUB_READ}")
    args = parser.parse_args()
    result = verify(args.pr_url, tuple(args.permission))
    print(json.dumps(asdict(result), indent=2))
    if result.status == Status.COMPLETED:
        return 3 if result.finding_count else 0
    return {Status.FAILED: 1, Status.BLOCKED: 2, Status.CANCELLED: 130}[result.status]


if __name__ == "__main__":
    raise SystemExit(main())
