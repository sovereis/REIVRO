"""Read-only Auth and Data API checks against the fixed staging project."""
import os
import sys
from uuid import UUID

from server import scop_firewall_checks as checks
from server.scop_firewall_pilot import STAGING


def verified_user(ref, key, token):
    if ref != STAGING:
        raise ValueError("Expected authorized staging")
    if not key.startswith("sb_publishable_") or not token or len(token.split(".")) != 3:
        raise ValueError("Expected a publishable key and a user JWT")
    user = checks._request("GET", f"https://{STAGING}.supabase.co/auth/v1/user",
                    {"apikey": key, "Authorization": "Bearer " + token})
    if user.get("role") != "authenticated" or user.get("is_anonymous") is not False:
        raise ValueError("Expected authenticated non-anonymous user")
    return UUID(user["id"])


def check_worker(env):
    ref = env["REIVRO_STAGING_REF"]
    key = env["REIVRO_PUBLISHABLE_KEY"]
    token = env["REIVRO_WORKER_JWT"]
    if verified_user(ref, key, token) != UUID(env["REIVRO_WORKER_USER_ID"]):
        raise ValueError("Worker Auth identity mismatch")
    memory = checks.StagingMemory(STAGING, key, token)
    if memory.read_run(1469495108, "00000000-0000-4000-8000-000000000000") is not None:
        raise ValueError("Unexpected result for reserved probe ID")


def main():
    try:
        check_worker(os.environ)
    except Exception:
        print("FAIL: staging Auth or read-only RPC check failed", file=sys.stderr)
        return 1
    print("PASS: staging Auth subject and read-only RPC verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
