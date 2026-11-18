"""Validate regression-test proposals and optionally check public issue quotes."""

import argparse
import json
import re
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ISSUE = re.compile(r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def texts(value):
    return isinstance(value, list) and bool(value) and all(map(text, value))


def fields(value, expected, label):
    require(isinstance(value, dict) and value.keys() == set(expected.split()),
            f"{label} has missing or unsupported fields")


def issue_parts(url):
    match = ISSUE.fullmatch(url) if isinstance(url, str) else None
    require(match and match[2] not in {".", ".."}, "invalid source issue URL")
    return match.groups()


def validate(record):
    fields(record, "issue_url status evidence proposal upstream_execution limitations", "record")
    issue_parts(record["issue_url"])
    require(record["status"] == "proposed", "unsupported result status")
    evidence = record["evidence"]
    require(isinstance(evidence, list), "evidence must be a list")
    roles = set()
    for item in evidence:
        fields(item, "role url quote", "source evidence")
        issue_parts(item["url"])
        require(item["role"] in ("trigger", "symptom"), "unsupported evidence role")
        require(text(item["quote"]), "source quotation required")
        roles.add(item["role"])
    require(roles == {"trigger", "symptom"}, "incomplete evidence: trigger and symptom required")
    require(any(item["url"] == record["issue_url"] for item in evidence),
            "primary issue reference required")

    proposal = record["proposal"]
    fields(proposal, "framework setup steps assertion predicted_failure rationale", "proposal")
    require(all(text(proposal[key]) for key in
                ("framework", "setup", "assertion", "predicted_failure", "rationale")),
            "proposal fields must contain text")
    require(proposal["rationale"].startswith("Inferred: "),
            "proposal rationale must identify inferred behavior")
    require(texts(proposal["steps"]), "proposal requires ordered steps")
    execution = record["upstream_execution"]
    fields(execution, "status reason", "upstream execution")
    require(execution["status"] == "not_run" and text(execution["reason"]),
            "unsupported upstream execution claim")
    require(texts(record["limitations"]), "limitations required")


def fetch_issue_body(url):
    owner, repo, number = issue_parts(url)
    endpoint = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    request = Request(endpoint, headers={"Accept": "application/vnd.github+json",
                                         "User-Agent": "SCOP-bug-regression-test"})
    with urlopen(request, timeout=20) as response:
        issue = json.load(response)
    require(isinstance(issue, dict) and issue.get("html_url") == url
            and "pull_request" not in issue, f"source is not the requested issue: {url}")
    return issue.get("body")


def verify_sources(record, fetch=fetch_issue_body):
    bodies = {}
    for item in record["evidence"]:
        url = item["url"]
        if url not in bodies:
            bodies[url] = fetch(url)
        body = bodies[url]
        require(isinstance(body, str) and item["quote"] in body,
                f"unsupported evidence quotation: {url} ({item['role']})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="match quotations against GitHub")
    parser.add_argument("records", nargs="*", type=Path)
    args = parser.parse_args()
    records = args.records or sorted(Path(__file__).parent.glob("*.json"))
    if not records:
        parser.error("no proposal records found")
    passed = blocked = failed = 0
    seen = set()
    for path in records:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            validate(record)
            identity = record["issue_url"].lower()
            require(identity not in seen, "duplicate issue record")
            seen.add(identity)
            if args.live:
                verify_sources(record)
        except (URLError, TimeoutError) as error:
            print(f"BLOCKED {path.name}: {error}")
            blocked += 1
        except (OSError, ValueError) as error:
            print(f"FAIL {path.name}: {error}")
            failed += 1
        else:
            print(f"PASS {path.name}: {'structure and live source quotes' if args.live else 'structure'}")
            passed += 1
    print(f"{passed} passed, {blocked} blocked, {failed} failed. Upstream tests executed: 0.")
    return 1 if failed else 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
