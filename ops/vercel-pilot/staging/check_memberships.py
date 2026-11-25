"""Read-only hosted Auth and RLS matrix using existing staging fixtures."""
import argparse
import os
import sys
from uuid import UUID

from check_worker import verified_user
from server.scop_firewall_checks import StagingMemory

MATRIX = (
    ("REIVRO_REVIEWER_JWT", (True, False)),
    ("REIVRO_VIEWER_JWT", (True, False)),
    ("REIVRO_WORKER_JWT", (False, False)),
    ("REIVRO_OTHER_REVIEWER_JWT", (False, True)),
    ("REIVRO_NO_MEMBERSHIP_JWT", (False, False)),
)


def check_memberships(env, *, reviewer_revoked=False):
    ref, key = env["REIVRO_STAGING_REF"], env["REIVRO_PUBLISHABLE_KEY"]
    fixtures = tuple((int(env[f"REIVRO_FIXTURE_{name}_REPOSITORY_ID"]),
                      str(UUID(env[f"REIVRO_FIXTURE_{name}_RUN_ID"]))) for name in ("A", "B"))
    if fixtures[0][0] == fixtures[1][0] or any(repo <= 0 for repo, _ in fixtures):
        raise ValueError("Expected two separate fixture repositories")
    identities = set()
    for variable, access in MATRIX:
        token = env[variable]
        identity = verified_user(ref, key, token)
        if identity in identities:
            raise ValueError("Expected five distinct Auth subjects")
        identities.add(identity)
        if variable == "REIVRO_WORKER_JWT" and identity != UUID(env["REIVRO_WORKER_USER_ID"]):
            raise ValueError("Worker Auth identity mismatch")
        if variable == "REIVRO_REVIEWER_JWT" and reviewer_revoked:
            access = (False, False)
        memory = StagingMemory(ref, key, token)
        for (repo, run_id), allowed in zip(fixtures, access):
            result = memory.read_run(repo, run_id)
            if allowed:
                if not isinstance(result, dict) or result.get("run", {}).get("id") != run_id:
                    raise ValueError("Expected fixture run")
            elif result is not None:
                raise ValueError("Unexpected fixture access")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer-revoked", action="store_true")
    options = parser.parse_args()
    try:
        check_memberships(os.environ, reviewer_revoked=options.reviewer_revoked)
    except Exception:
        print("FAIL: staging Auth or RLS matrix could not be verified", file=sys.stderr)
        return 1
    print("PASS: five staging Auth subjects and ten read-only RPC checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
