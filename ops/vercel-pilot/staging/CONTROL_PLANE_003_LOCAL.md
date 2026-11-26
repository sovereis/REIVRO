# Migration 003 operational script: local Git delivery

This branch contains only the readable operational script and these instructions
on top of approved commit `e280fa4f096ff7aa4d6d190d678982d3ea26fe49`.
The original SQL migrations are unchanged. Publishing this branch does not authorize
ledger writes, applying migration 003, resuming writers, or any deployment.

## Scope and prerequisites

- Windows PowerShell 5.1-compatible syntax and .NET APIs; Windows execution remains
  unvalidated. Offline preparation and failure controls were tested using
  PowerShell 7.4.6 on Linux, not a second Windows machine.
- Git for Windows (`git.exe`) on PATH, with the approved commit available locally.
- PostgreSQL 19 client tools for connected modes; default executable:
  `C:\Program Files\PostgreSQL\19\bin\psql.exe`.
- Use a protected operator directory and a fresh output directory. Keep backups and
  receipts private; do not commit them.
- Connected modes use only the staging Session Pooler:
  `aws-1-us-west-1.pooler.supabase.com:5432`, database `postgres`, user
  `postgres.lbklqqqbmeyseeccdqog`, SSL `verify-full` and manual `-W` authentication.
  Retain the founder's previously validated trusted root certificate configuration.
  No credential should be pasted into chat or placed on the command line.

## Verify the script

Canonical format: UTF-8 without BOM, LF, one final newline.
Script SHA256:

```text
d98931ca01de7a3a37229230c2aef6ad302689bdd4ed495b69e83760f8d128a0
```

The script reads Git blobs directly from the approved commit, rather than reading
possibly modified working-tree SQL files. It disables Git replacement objects,
checks native Git exit status, strictly decodes UTF-8, normalizes LF, and checks
these source hashes:

| Approved SQL | SHA256 |
| --- | --- |
| `supabase/staging/002_durable_execution.sql` | `2ea6824530ffed52a33f6ac449f0b396f19b24d511eef092fc713bea10c39fb4` |
| `supabase/staging/003_control_plane.sql` | `6ffe1673191eac4335c3798daf9d3c34cb01551f9f674dd9ebdfa31215c88c19` |

It never checks out files over existing work. There is no Base64, compression,
remote download, automatic SQL execution in Prepare, or credential embedded.

## Prepare only

From the operational worktree root, run this PowerShell block. Adjust the output
path to a fresh directory inside the operator's protected storage.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $Repo = (Get-Location).Path
    $Script = Join-Path $Repo 'ops\vercel-pilot\staging\control-plane-003-local.ps1'
    $Work = 'C:\REIVRO-ops\kit-003-local-v1'
    $Utf8 = New-Object System.Text.UTF8Encoding($false)
    $Text = [IO.File]::ReadAllText($Script)
    $Text = $Text.Replace("`r`n", "`n").TrimEnd([char[]]"`r`n") + "`n"
    [IO.File]::WriteAllText($Script, $Text, $Utf8)
    $Expected = 'd98931ca01de7a3a37229230c2aef6ad302689bdd4ed495b69e83760f8d128a0'
    if ((Get-FileHash -LiteralPath $Script -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected) {
        throw 'Script SHA256 mismatch. Stop.'
    }
    & $Script -Mode Prepare -Repo $Repo -Work $Work
}
```

Stop at `PASS: files prepared. No database connection was made.` Prepare emits
readable SQL files and a `sha256.json` manifest. Later modes recompute expected
contents from the pinned source and readable script guards; they do not trust a
modified manifest. Never use a partially prepared output directory after failure.

## Separate operational phases

The following modes are independent invocations, never an automatic pipeline.
This publication instructs the operator to run only Prepare.

| Mode | Effect |
| --- | --- |
| `Prepare` (default) | Offline file generation; no database connection |
| `Audit002` | Read-only V2 checks and preservation of the historical data baseline |
| `Inspect` | Read-only function fingerprints, ledger metadata and active transactions |
| `Ledger002` | Explicit ledger-only write; requires `-ConfirmAction RECONCILE-002-STAGING`; never executes migration 002 again |
| `Preflight003` | Read-only V2/data checks and verification of the reconciled ledger |
| `Apply003` | Future explicitly confirmed transaction; requires `-ConfirmAction APPLY-003-STAGING` |
| `Postcheck003` | Read-only V3/security/data and ledger checks before fixtures are created |

Read-only example, only when the founder proceeds to the audit phase:

```powershell
& $Script -Mode Audit002 -Repo $Repo -Work $Work
```

Supply `$Script`, `$Repo`, and `$Work` in the current PowerShell session first;
the variables in the Prepare example's script block do not persist outside it.

### Ledger bookkeeping

Version `20261126000200`, name `reivro_durable_execution_002`, is a proposed
canonical bookkeeping identifier, not a claim about the actual application time.
Ledger002 verifies the existing V2 state and historical data before recording the
approved SQL as inert text. A conflicting existing record causes failure. It does
not execute that stored SQL text.

Future migration 003 uses version `20261126000300`, name
`reivro_control_plane_003`; its ledger entry is written in the same transaction as
the migration and its pre-commit checks. Do not use `supabase db push` or a blanket
migration replay as a substitute for this narrowly scoped reconciliation.

### Transaction and uncertain commit

- All executed SQL is passed using `psql -f`, with `-X`, `ON_ERROR_STOP=1`, manual
  `-W` authentication and an explicit native exit-code check.
- Write phases acquire an advisory lock and table locks, repeat the blocking
  checks, and use one transaction. SQL failure before COMMIT rolls back on session
  termination. Migration 003 reuses the exact approved body between its original
  transaction boundaries, with guards and ledger insertion in the outer transaction.
- Data baseline checks are deliberately fixed to the audited staging state: seven
  table digests, zero pending runs, 12 events and sequence `12/true`. Drift is a
  blocking condition, never a reason to edit hashes just to obtain PASS.
- A lost connection or nonzero client exit during a write may mean an uncertain
  commit. Keep writers frozen. Do not retry automatically. Run Inspect, then the
  corresponding read-only Audit002/Preflight003 or Postcheck003 checks and inspect
  the private receipts and ledger before deciding the next action.
- Do not reapply 002. Do not blindly replay 003. Mixed, conflicting, or unexpected
  state requires investigation before any further write.
- Postcheck003 intentionally expects no task fixtures yet. Do not reuse its empty
  fixture assertions after the separate authorized JWT validation phase begins.

## Delivery checks and limitations

Verified locally: source blobs equal the approved Git bytes; source hashes match;
script and generated SQL/text files have LF and no BOM; PowerShell parser accepts
the script; Prepare succeeds; an existing output directory, missing write-mode
confirmation, adulterated generated SQL and missing psql terminate execution;
process environment variables are restored after failure.

No migration or ledger write was executed for these delivery checks. They do not
validate hosted JWTs, Windows PowerShell execution, hosted security boundaries,
or private alpha readiness. Review the live staging state again before each
subsequently authorized operational phase.
