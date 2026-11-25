"""Read-only Auth and Data API checks against the fixed staging project."""
import os
import sys
from uuid import UUID

from server.scop_firewall_checks import StagingMemory, _request
from server.scop_firewall_pilot import STAGING


def check_worker(env):
    if env["REIVRO_STAGING_REF"] != STAGING:
        raise ValueError("Expected authorized staging")
    key = env["REIVRO_PUBLISHABLE_KEY"]
    token = env["REIVRO_WORKER_JWT"]
    if not token or len(token.split(".")) != 3:
        raise ValueError("Expected a user JWT")
    expected = UUID(env["REIVRO_WORKER_USER_ID"])
    memory = StagingMemory(STAGING, key, token)
    user = _request("GET", f"https://{STAGING}.supabase.co/auth/v1/user",
                    {"apikey": key, "Authorization": "Bearer " + token})
    if UUID(user["id"]) != expected or user.get("role") != "authenticated" or user.get("is_anonymous") is not False:
        raise ValueError("Worker Auth identity mismatch")
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
