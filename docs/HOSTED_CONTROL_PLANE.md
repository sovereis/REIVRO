# Hosted control plane foundation V1

Base 9444d213be0907ad77ee6a2d77c3bf17101cd1e6. Candidate 003 follows 001 and 002 in a single transaction. No hosted application is authorized by this document. The local SQLite Developer Preview is unchanged.

## Authorization

| Identity | Allowed operations |
| --- | --- |
| agent | submit against an approved contract, read its own submissions |
| reviewer | approve contract versions, read submissions, confirm failures, approve/revoke task policies, grant corrections |
| worker | read, claim, renew, fail and finish task runs |
| viewer | read project submissions |
| absent or other project | denied |

Authorization uses auth.uid() and locked membership rows. User-editable metadata is never consulted. An agent has one project role and cannot upgrade it. A worker cannot make human decisions. All four new tables have RLS enabled and no direct client grants, including reads. The exposed security-invoker RPC delegates to a private security-definer function with an empty search_path and explicit execute grants. Database administrators remain trusted.

Reviewer tokens must stay in an operator context inaccessible to the agent. Use a separate operator device or a properly isolated OS account/browser profile with no shared credentials, debug channel or readable token store. A reviewer login in the same agent-controlled OS account is insufficient. A future independent web approval session should authenticate the human separately. No reviewer or administrative token is sent in an agent submission, queue item, sandbox environment, or report.

## Persistence and identity

Contracts are identified by project, UUID and positive version. Approval inserts immutable document bytes represented as PostgreSQL JSONB and binds a SHA-256 digest to its JSONB text representation. This hosted digest format is distinct from the local task-identifier encoding. The future adapter must obtain and compare the server-approved digest, never reinterpret a local digest as a hosted one. BASE is fixed in the approved document. A new version requires a new reviewer approval. There is no client mutation or deletion operation.

Submissions bind authenticated agent, contract/version/digest, BASE, HEAD and task-completion-v1. IDs are client-generated UUIDs. Each agent has one root submission per approved contract version. A subsequent submission requires a consumed correction grant or a newly approved contract version, preventing omission of the parent field from bypassing correction authorization. Exact replays return duplicate without another submission event. Changed content under the same ID is rejected. Project membership is checked on every RPC. A submission without a persisted result is pending or inconclusive for clients, never verified.

A worker claims through task_dispatch. It supplies the matching digest, revisions, verifier, and existing GitHub execution scope. The claim delegates to the private execution_dispatch helper derived from 002 and shares the existing runs, execution_leases and audit events. The response contains the approved contract, policy documents and their digests, attempt ID and fencing token. Claim identity checks remain independent of any agent completion claim. This foundation still uses the existing PR-shaped execution envelope; a future general task adapter must resolve real repository scope rather than invent installation IDs.

Renewal and failure delegate to the shared private Durable Execution helper. Finish checks worker ownership and a live attempt through that RPC, validates result binding, evidence digest and the captured policy set, then records result and closes the lease transactionally. The worker is the trusted evidence authority. Structural validation in SQL does not prove the semantic truth of worker-produced evidence. Execution failures have a retryable fail transition; explicit ERROR completion is terminal. Clients must retry transport failures and reconcile persisted state before ACK. Delivery is at least once with idempotent effects.

Task statuses are VERIFIED, INCOMPLETE, POLICY_VIOLATION, INCONCLUSIVE and ERROR. Shared legacy runs deliberately store INCONCLUSIVE for non-error task results, avoiding interpretation as a successful syntax check. Consumers read the authoritative task result through task_dispatch read. A completed task run is not re-executed on replay.

## Policies and human decisions

Syntax protections retain one_active_guard and their unchanged dispatcher. Task policy sets live in reivro_cloud.task_policies under the same project and journal. This resolves the project-wide task-policy cardinality requirement without permitting multiple active syntax guards. Policy documents are operator-selected static predicates using exists, blob_sha256, protected_path and allowed_paths. The worker must validate and evaluate the full documents with the existing policy implementation before emitting a result. Malformed, conflicting or unsupported policy documents require inconclusion.

A policy requires a worker-produced failure and explicit reviewer confirmation. Policies are immutable except for revocation. Versioned replacement uses a fresh policy ID. Revocation and task finalization take the same project lock. If the approved set differs from the claim snapshot, finish persists INCONCLUSIVE, even if a worker submitted VERIFIED. A changed set is re-evaluated only in a fresh submission.

Correction grants are reviewer-only, single use and limited to two per contract. Submission of a correction binds the same authenticated agent, contract version, a different HEAD and a parent failure. Consuming a grant and inserting the submission occur in one transaction. A replay does not consume another grant. These controls authorize submission for correction; enforcement against an agent modifying its own workspace remains outside this control plane.

## Future transport contracts

The CLI remote mode will send a bounded versioned JSON request over authenticated HTTPS and retain the existing local mode. It must expose contract digest, task UUID, event UUID and requested revision in its feedback. A separate reviewer client issues human decisions. Neither API nor queue accepts an agent-supplied authoritative result.

The API will translate authenticated submissions to execution references. Queue messages contain submission IDs and approved project scope, without reviewer credentials. A trusted worker resolves the approved contract and artifact set, independently verifies Git revisions and evaluates the task using the existing verifier. Finish accepts only that worker's identity and active attempt. Sandbox execution remains credential-free and separately validated. Functional execution stays disabled.

The local artifact/export path remains versionable. Hosted approval and revocation are authoritative for remote runs, with digest-checked local artifacts as a cache. An unavailable authority cannot produce a favorable remote decision.

## Reproduce locally

    PYTHON=python3 bash scripts/test-control-plane.sh
    python3 -m pytest -q

The dedicated runner creates PostgreSQL 17 without network, applies 001, 002 and 003, runs existing syntax and recovery tests plus the new authorization tests, and destroys the container. Auth subjects are simulated PostgreSQL request claims, not staging JWTs. The dump/restore case restores into a new disposable database and verifies persisted human confirmation.

Before any hosted change, obtain separate founder authorization for migration review/application and synthetic writes. Confirm actual worker/reviewer/agent logins, RLS and RPC behavior through the Data API, restoration, and token separation. Private Alpha remains blocked.

## Mission 6.3 evidence

The foundation is tested using synthetic Auth subjects inside disposable PostgreSQL 17. These tests exercise the real SQL authorization and transactions. They do not validate hosted JWT issuance, PostgREST exposure, Vercel execution, or actual separation of operator credentials from an agent process.

Positive tests cover reviewer-approved immutable contracts, agent submissions, viewer reads, trusted-worker completion, correction grants, multiple task policies, human confirmation, revocation and database dump/restore. Negative tests cover agent and worker human decisions, absent and cross-project memberships, direct writes, contract replacement, conflicting event replay, divergent execution identity, forged result structure, revoked worker membership, expired leases and old fencing tokens. Two concurrent submissions persist one root event. Revocation during an in-flight execution changes the final status to INCONCLUSIVE. A second database restored from pg_dump preserves confirmation and revocation.

| Suite | Observed result |
| --- | --- |
| Standard local pytest | 265 passed, 23 skipped |
| New migration plus existing PostgreSQL syntax/recovery suites | 35 passed |
| Existing opt-in task and task Firewall suites | 21 passed |
| Chromium UI | 10 passed |
| Effectiveness V1 and V2 | 2 passed each |
| Functional declarative benchmark | 17 expected observations matched |
| Task benchmark | 30 expected observations matched |
| Task Firewall benchmark | 15 expected observations matched |
| Live GitHub pytest | 265 passed, 18 skipped, 5 failed |

The five live GitHub failures remain in measurement, PR summary, web HTTP, workflow and workspace integration. No tests were disabled to suppress them. No hosted readiness claim depends on them passing. Additional skips reflect opt-in and disposable PostgreSQL tests, which were run through their dedicated harnesses where applicable.

Shell syntax, Python compilation, Git whitespace review and a credential-pattern scan passed. Existing server code, SQLite behavior and the Developer Preview launcher are unchanged from the required base.

Remaining limits include a trusted worker responsible for semantic evidence validation, no remote CLI/API/queue task transport implementation, no hosted migration application, no actual JWT authorization matrix, and no validated reviewer credential separation on the same machine. PostgreSQL administrators and hosting administrators remain trusted. A worker compromise is not prevented by RLS.

The next operation requiring founder authorization is a reviewed staging-only migration and synthetic-write rehearsal after checking the existing 001/002 state, backup/restore plan and independent identities. The current branch alone grants no authorization to apply 002 or 003, deploy, spend, or release the Private Alpha.

## Execution identity correction after staging preflight

The staging preflight identified that task claims reused syntax's revision-only key. A completed syntax run could therefore make a new task claim appear completed with no persisted task result. Multiple contracts at the same revision could also collide. The earlier authorization tests did not cover those combinations.

The revised candidate 003 adds task_submission_id to the shared runs table. Existing rows remain syntax runs with NULL task_submission_id. Partial unique indexes retain delivery and revision deduplication for syntax. Task runs are unique per project and immutable submission UUID, which already binds authenticated actor, contract version/digest, BASE, HEAD and verifier. Distinct submissions cannot inherit one another's completion. The submission UUID is also used as the task run's delivery identity, without changing its actual PR or revision references.

Both namespaces use a private execution_dispatch state machine containing the existing 002 lease, attempt, fencing, renewal and failure behavior. The legacy dispatch endpoint supplies the syntax namespace. Task operations supply the bound submission UUID. The private helper has no client execute grants. Legacy renewal/finalization cannot target a task run. Reviewer decisions and syntax's one_active_guard remain unchanged.

The migration now requires the exact reviewed 001 and 002 function hashes, rejects a partial or previous 003 application, takes the existing advisory migration lock and sets bounded lock/statement timeouts. It remains transactional and must not be blindly replayed after a lost commit response.

Regression cases cover syntax running before task, syntax completed before task, task created before syntax, two contracts at the same PR/BASE/HEAD with concurrent redelivery, attempted legacy renewal of a task run, and completed syntax history seeded before applying 003. These remain disposable PostgreSQL tests with synthetic request identities.

The founder authorized continuation after mission 6.4. Hosted migration application remains technically blocked pending a verified backup/restoration path and actual login credentials. This session has no PGPASSFILE, PGSSLROOTCERT, publishable key, or role JWT variables. The administrative SQL connector does not provide an independently validated backup/restore workflow or establish role-token authorization. No hosted migration or fixture write was performed as part of this correction. Authorization does not establish that these prerequisites have passed.

Configure the staging-specific PostgreSQL credential file through the secure environment, together with a trusted TLS CA, and choose an operator-controlled encrypted backup destination. Never put the password in the chat, command arguments, source tree or logs. Provide publishable-key and short-lived agent/reviewer/worker/viewer/no-membership tokens through their appropriate isolated processes for the future authorization matrix. Reviewer credentials must never be exposed to the agent process. Restoring and comparing the backup precedes any hosted schema change.

After the correction, the shared disposable PostgreSQL harness passed 40 tests in 36.40 seconds, including all previous 29 syntax/recovery tests. The standard suite passed 265 tests with 28 opt-in skips in 18.64 seconds. Hosted backup recovery, real JWT authorization and Private Alpha remain blocked by the prerequisites above.
