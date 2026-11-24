# REIVRO Rework Firewall Alpha

The local alpha turns a verified Python syntax regression into a repository protection that an operator can approve and run on a later public GitHub PR. A violation result records a detected recurrence. The CLI has no GitHub write or merge enforcement integration.

## Components and ownership

- **VERIFY** uses [the existing syntax rule](../server/VERIFY.md). A complete `REGRESSION_DETECTED` report produces a stable finding ID derived from the repository, PR, pinned BASE and HEAD SHAs, compiler, verifier version, and finding evidence. A suspect or ambiguous diagnostic stays in an inconclusive analysis. An operational failure is recorded as an error.
- **CONFIRM and LEARN** use an owner-only SQLite database outside the checkout. One database belongs to one repository and one effective OS UID. Project metadata and the transactional event journal record analyses, findings, confirmed or rejected failures, proposals, approvals, revocations, exports and protection runs. Decisions include the UID, UTC timestamp, justification and evidence or artifact digest. A finding decision and a protection decision are separate. Rejected findings and rejected or revoked protections remain terminal in the alpha.
- **Repository Memory** is an approved JSON manifest under `.reivro/protections/<id>.json`. It contains a version, original finding ID, scope, trigger, approval metadata and an allowlisted executable rule identifier. The CLI dispatches that identifier to VERIFY directly. The manifest contains no source excerpts, tokens, approval reasons or commands to run. Deliberate export creates a new file without overwriting an existing one.
- **PREVENT** takes a protection ID and a target PR. It loads the exact approved manifest from the selected checkout, checks current approval in the project journal, then runs the same verifier. A changed manifest, missing file or revoked approval cannot authorize execution. Approval, stored evidence digests and current artifact bytes are checked again before recording the outcome. A HEAD matching the original failure is inapplicable. A keyboard interrupt during verification is recorded as an error. Abrupt process termination can leave a started run without a completion event.
- **Metrics** count analyses, decisions, proposed and approved protections, completed protection executions, detected recurrences, inconclusive results and analysis time. Recurrences are counted per run. Cost is null because the alpha has no billing meter.

## CLI

Run from this repository with CPython 3.12 on Linux and `libseccomp.so.2`. Use a private directory outside Git and the public repository you want to analyze. The same OS user runs all commands for that project. Use a trusted checkout path for export and execution.

```sh
STORE=/absolute/private/memory
REPO=owner/repository
CHECKOUT=/absolute/checkout
firewall() { python -B -m server.scop_firewall --store "$STORE" --repository "$REPO" "$@"; }

firewall init
firewall analyze https://github.com/owner/repository/pull/1 --github-read
firewall show "$FINDING_ID"
firewall review "$FINDING_ID" confirm --reason "Reviewed pinned syntax evidence"
firewall propose "$FINDING_ID"
firewall decide "$PROTECTION_ID" approve --reason "Reviewed the proposed scope and rule"
firewall export "$PROTECTION_ID" --checkout "$CHECKOUT"
firewall run "$PROTECTION_ID" https://github.com/owner/repository/pull/2 --checkout "$CHECKOUT" --github-read
firewall show "$RUN_ID"
firewall show "$ANALYSIS_ID"
firewall metrics
firewall decide "$PROTECTION_ID" revoke --reason "Guard retired for this project"
```

Copy the IDs from each preceding JSON result. `review ... reject` and `decide ... reject` record separate negative decisions. `show` lists the journal or filters by exact ID. `run` statuses are `VIOLATION_DETECTED`, `NO_VIOLATION`, `INCONCLUSIVE`, `ERROR` and `INAPPLICABLE`. The CLI uses exit 3 for detected violations or findings, 2 for inconclusive or inapplicable results, 1 for errors and 0 for successful commands or a clean check.

## Reproduce the complete cycle

```sh
python -m pytest -q tests/test_scop_firewall.py::test_cycle_through_cli_with_git_versioned_artifact
```

The test calls the CLI entry point with simulated, explicit developer decisions, a real SQLite database and the real isolated CPython verifier. It supplies controlled GitHub responses. In PR 1, `first.py` changes from `x = 1` to `x = )`. A reviewer confirms the finding and separately approves the manifest. The test stages the file in a disposable Git index, restores it from that index and applies it to PR 2. The different HEAD and `future.py` reproduce the syntax category and yield `VIOLATION_DETECTED`. A third PR yields `NO_VIOLATION`. Fixtures use synthetic repository names and SHAs.

## Trust boundaries and future integrations

The alpha trusts the OS account, its private SQLite directory and its parent directories. A process with that UID can change the database or invoke explicit approval commands. The journal provides application-level audit history, without independent human identity, cryptographic attestation or tamper resistance against the owner. Use a trusted copy of the CLI outside the reviewed PR checkout in future automation. The artifact is portable in Git; activation requires the corresponding project journal, which also makes old exports ineffective after revocation. Filesystem export and SQLite are separate resources. If export succeeds but the journal write fails, review the manifest on disk against the approved state before retrying.

The existing production Supabase path serves Early Access through a restricted signup RPC. The alpha uses separate local storage. [The Cloud Memory SQL review draft](FIREWALL_CLOUD_DRAFT.sql) models the separate project, membership and event journal tables with default-deny access. It is not wired into the CLI or the existing signup schema. Before using it, create a formal migration for an isolated staging Supabase project and verify the schema and deny-by-default behavior with test queries. Then design a server-side append API that verifies user identity and project membership, serializes decisions, validates event payloads and derives actor identity and timestamps on the server. Test tenant isolation for reads, approvals, executions and revocations before granting access. The draft foreign keys enforce project and user existence. They do not prove actor membership, validate commit SHAs in event JSON or enforce approval and revocation ordering. Before granting any service access, define per-project authorization and transaction locking for state transitions, an audited service identity, and retention rules that account for user deletion and historical references.

For GitHub integration, review a trusted installation and least-privilege pull request access. Resolve the approved manifest at a trusted base commit and obtain active state from Cloud Memory. Run against the pinned PR revision and expose an evidence-linked check result. Require a separate decision for any future branch protection or merge gating. The current alpha reads public PR evidence and writes only to the chosen local memory and explicit export path.

The draft was applied in a disposable PostgreSQL 17 instance with stub Supabase roles and an `auth.users` table. Catalog checks confirmed RLS on all three tables and denied schema or event-table access to `anon`, `authenticated` and `service_role`. Supabase staging validation remains pending.
