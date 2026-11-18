"""Validate PR summary records, optionally checking excerpts against GitHub."""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


PR_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/([1-9][0-9]*)", re.ASCII)

HUNK_HEADER = re.compile(r"^@@ -[0-9]+(?:,[0-9]+)? \+[0-9]+(?:,[0-9]+)? @@")
REQUIRED_PRS = {
    ("pallets", "flask", "5898"),
    ("pallets", "flask", "5808"),
    ("pytest-dev", "pytest", "12022"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate(record):
    fields = {"pr_url", "checked_on", "status", "verified_facts", "assumptions",
              "limitations", "blocked_reason"}
    require(isinstance(record, dict) and fields <= record.keys(), "missing record fields")
    url = record["pr_url"]
    match = PR_URL.fullmatch(url) if isinstance(url, str) else None
    require(match and all(part not in {".", ".."} for part in match.groups()[:2]),
            "invalid canonical GitHub PR URL")
    observed = record["checked_on"]
    require(isinstance(observed, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", observed),
            "expected YYYY-MM-DD observation date")
    date.fromisoformat(observed)
    for field in ("assumptions", "limitations"):
        values = record[field]
        require(isinstance(values, list) and all(map(nonempty, values)), f"invalid {field}")
    facts = record["verified_facts"]
    require(isinstance(facts, list), "verified_facts must be an array")
    if record["status"] == "blocked":
        require(nonempty(record["blocked_reason"]) and not facts and not record["assumptions"],
                "blocked records require a reason and empty facts and assumptions")
        return match.groups(), []

    require(record["status"] == "summarized" and record["blocked_reason"] is None and facts,
            "summarized records require facts and a null blocked_reason")
    sources = []
    for fact in facts:
        require(isinstance(fact, dict) and nonempty(fact.get("claim")), "missing fact claim")
        refs = fact.get("sources")
        require(isinstance(refs, list) and refs, "fact has no sources")
        for source in refs:
            require(isinstance(source, dict) and all(
                nonempty(source.get(key)) for key in ("kind", "url", "locator", "excerpt")
            ), "invalid source fields")
            kind, locator = source["kind"], source["locator"]
            expected = url
            if kind == "diff":
                require(all(line.startswith(("+", "-", " "))
                            for line in source["excerpt"].split("\n")),
                        "diff excerpt lines must start with +, -, or a context space")
                digest = hashlib.sha256(locator.encode("utf-8")).hexdigest()
                expected += f"/files#diff-{digest}"
            elif kind == "description":
                require(locator == "body", "description locator must be body")
            else:
                require(kind == "metadata" and re.fullmatch(r"[a-z][a-z0-9_]*", locator)
                        and locator != "body", "invalid metadata locator or source kind")
            require(source["url"] == expected, f"source URL does not match PR and locator: {locator}")
            sources.append(source)
    require(any(source["kind"] == "diff" for source in sources), "missing diff reference")
    return match.groups(), sources


def suite_errors(identities):
    counts = Counter((owner.lower(), repo.lower(), number)
                     for owner, repo, number in identities)
    for label, identities in (
        ("missing required PR", REQUIRED_PRS - counts.keys()),
        ("duplicate PR", {identity for identity, count in counts.items() if count > 1}),
        ("unexpected PR", counts.keys() - REQUIRED_PRS),
    ):
        for owner, repo, number in sorted(identities):
            yield f"{label}: {owner}/{repo}#{number}"


def diff_excerpt_matches(patch, excerpt):
    """Match consecutive full lines within a single unified diff hunk."""
    if not isinstance(patch, str):
        return False
    quoted_lines = excerpt.split("\n")
    hunk_lines = []
    in_hunk = False
    for line in patch.split("\n"):
        if HUNK_HEADER.match(line):
            in_hunk = True
            hunk_lines.clear()
        elif in_hunk and line.startswith(("+", "-", " ")):
            hunk_lines.append(line)
            if hunk_lines[-len(quoted_lines):] == quoted_lines:
                return True
        elif in_hunk and line == r"\ No newline at end of file":
            hunk_lines.clear()
        else:
            in_hunk = False
    return False


def github_json(url):
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "SCOP-pr-source-summary-validator",
    })
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def verify_live(identity, sources):
    owner, repo, number = identity
    endpoint = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
    metadata = github_json(endpoint)
    require(metadata.get("html_url") == f"https://github.com/{owner}/{repo}/pull/{number}",
            "GitHub returned a different PR URL")
    needed = {s["locator"] for s in sources if s["kind"] == "diff"}
    patches = {}
    # GitHub exposes at most 3,000 files through this endpoint.
    for page in range(1, 31):
        files = github_json(f"{endpoint}/files?per_page=100&page={page}")
        patches.update((file["filename"], file.get("patch")) for file in files)
        if needed <= patches.keys() or len(files) < 100:
            break
    for source in sources:
        kind, locator, excerpt = source["kind"], source["locator"], source["excerpt"]
        if kind == "metadata":
            value = metadata.get(locator)
            if isinstance(value, (bool, int, float)):
                value = json.dumps(value)
            matched = value == excerpt
        elif kind == "diff":
            matched = diff_excerpt_matches(patches.get(locator), excerpt)
        else:
            value = metadata.get("body")
            matched = isinstance(value, str) and excerpt in value
        require(matched, f"GitHub evidence is absent or does not match: {kind} {locator}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="verify excerpts with GitHub")
    parser.add_argument("records", nargs="*", type=Path, help="defaults to adjacent JSON records")
    args = parser.parse_args()
    paths = args.records or sorted(Path(__file__).parent.glob("*.json"))
    records = []
    failed = 0
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            identity, sources = validate(record)
        except (OSError, ValueError) as error:
            print(f"FAIL {path.name}: {error}")
            failed += 1
            continue
        records.append((path, record, identity, sources))

    errors = list(suite_errors(identity for _, _, identity, _ in records))
    for error in errors:
        print(f"FAIL suite: {error}")
    if errors or failed:
        print(f"0 passed, 0 blocked, {failed + len(errors)} failed checks")
        return 1

    passed = blocked = 0
    for path, record, identity, sources in records:
        if record["status"] == "blocked":
            print(f"BLOCKED {path.name}: {record['blocked_reason']}")
            blocked += 1
            continue
        try:
            if args.live:
                verify_live(identity, sources)
        except (URLError, TimeoutError) as error:
            print(f"BLOCKED {path.name}: live GitHub verification unavailable: {error}")
            blocked += 1
        except ValueError as error:
            print(f"FAIL {path.name}: {error}")
            failed += 1
        else:
            mode = "structure and live evidence" if args.live else "structure and reference format"
            print(f"PASS {path.name}: {len(sources)} references checked ({mode})")
            passed += 1
    print(f"{passed} passed, {blocked} blocked, {failed} failed")
    return 1 if failed else 2 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
