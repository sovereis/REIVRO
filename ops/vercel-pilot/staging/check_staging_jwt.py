#!/usr/bin/env python3
"""Check one real staging identity and the legacy read-only RLS matrix."""
import argparse
import getpass
import json
import re
import sys
import urllib.error
import urllib.request
import uuid
import warnings


STAGING = "https://lbklqqqbmeyseeccdqog.supabase.co"
EXPECTED = {
    "reviewer-a": (True, False),
    "viewer-a": (True, False),
    "worker-a": (False, False),
    "agent-a": (False, False),
    "reviewer-b": (False, True),
    "sem-vinculo": (False, False),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(opener, headers, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(STAGING + path, data=data, headers=headers)
    with opener.open(req, timeout=15) as response:
        return json.load(response)


def repository_id(value):
    number = int(value)
    if not 0 < number < 2**63:
        raise argparse.ArgumentTypeError("repository ID outside bigint range")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("subject", choices=EXPECTED)
    parser.add_argument("--user-id", required=True, type=uuid.UUID)
    for scope in ("a", "b"):
        parser.add_argument(f"--repo-{scope}", required=True, type=repository_id)
        parser.add_argument(f"--run-{scope}", required=True, type=uuid.UUID)
    args = parser.parse_args()
    if args.repo_a == args.repo_b or args.run_a == args.run_b:
        parser.error("use distinct synthetic projects and runs")

    warnings.simplefilter("error", getpass.GetPassWarning)
    try:
        key = getpass.getpass("Staging publishable key: ").strip()
        token = getpass.getpass("Staging user JWT: ").strip()
        if not re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", key):
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2}", token):
            raise ValueError
    except (ValueError, EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print("FAIL: use a secure terminal with a publishable key and user JWT")
        return 1

    opener = urllib.request.build_opener(NoRedirect())
    headers = {"apikey": key, "Authorization": "Bearer " + token}
    step = "auth"
    try:
        user = request(opener, headers, "/auth/v1/user")
        if not isinstance(user, dict) or user.get("id") != str(args.user_id) or user.get("is_anonymous") is not False:
            raise ValueError
        print(f"PASS {args.subject} auth")
        headers.update({"Content-Type": "application/json", "Content-Profile": "reivro_checks_api"})
        fixtures = ((args.repo_a, args.run_a), (args.repo_b, args.run_b))
        for scope, (repo, run), allowed in zip(("A", "B"), fixtures, EXPECTED[args.subject]):
            step = f"legacy read {scope}"
            result = request(opener, headers, "/rest/v1/rpc/read_run",
                             {"p_repository_id": repo, "p_run_id": str(run)})
            if allowed:
                if not isinstance(result, dict) or not isinstance(result.get("run"), dict):
                    raise ValueError
                if result["run"].get("id") != str(run) or result["run"].get("task_submission_id") is not None:
                    raise ValueError
            elif result is not None:
                raise ValueError
            print(f"PASS {args.subject} {step}")
    except urllib.error.HTTPError as error:
        print(f"FAIL {args.subject} {step} HTTP {error.code}")
        return 1
    except (OSError, ValueError):
        print(f"FAIL {args.subject} {step} transport or unexpected response")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
