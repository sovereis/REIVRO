# REIVRO private alpha kit

## Getting Started

Use the [Developer Preview guide](../DEVELOPER_PREVIEW.md) to run the local static verifier. Start with `reivro demo`. Its tasks and agent labels are synthetic. All approvals in this demo are scripted operator decisions.

## Installation Guide

Use Linux or WSL, Python 3.10 or later, and Git at /usr/bin/git. WSL requires validation on an actual Windows host before alpha acceptance.

An operator installs a pinned, reviewed clone outside the agent account's write access. Record the commit before installing.

```bash
git rev-parse HEAD
git status --porcelain
git fsck --no-dangling
mkdir -p "$HOME/.local/bin"
ln -s "$REIVRO_SOURCE/reivro" "$HOME/.local/bin/reivro"
export PATH="$HOME/.local/bin:$PATH"
reivro --help
reivro --json demo
```

A clean status and the expected commit are required. Compare the SHA through the founder's trusted channel. Git object integrity alone does not establish publisher identity.

For an update, stop the CLI, back up the private journal, and install a separate clean clone at the newly approved SHA. Test the demo there before moving the launcher to that clone. Retain the previous clone and journal backup for rollback. Use an operator-owned source directory and parent directories. Inspect their ownership and permissions with `namei -l "$REIVRO_SOURCE/reivro"`.

Remove the launcher with `unlink "$HOME/.local/bin/reivro"`. Keep the journal until the operator explicitly decides to delete the retained evidence.

## First Verification

The complete contract, submission schema, review commands, and correction commands are in the Developer Preview guide. In the operator checkout:

```bash
export REIVRO_PROJECT=your-org/your-repo
export REIVRO_STORE="$HOME/.reivro-your-repo"
reivro init
reivro doctor
reivro task approve < contract.json
reivro --json verify "$TASK_DIGEST" < submission.json
```

Save the task digest and event ID. Criteria must be approved at BASE before agent work. A candidate commit must be imported without running its hooks, tests, filters, or scripts. Keep the operator checkout under operator control.

## Security Model

The operator controls approval commands, journal, runtime artifacts, launcher, source, and process environment. The agent works under a different OS identity with no sudo, Docker socket access, shared writable operator directories, or operator credentials. The agent receives a copy of task instructions and submits commit references. Copy sanitized reports back through an operator-controlled handoff.

An agent running as the operator can invoke the same approval commands and access the journal. Separate OS identities and filesystem access controls are a prerequisite for this alpha. Test the deployment's actual accounts before admitting a participant.

The disposable boundary probe uses two distinct container UIDs. It tests private filesystem access and source write denial with synthetic files. It does not prove isolation of this Cloud agent from its own host identity, nor validate approval commands under a second host account. Docker socket access grants control over containers and must remain with the operator.

## Recovery and Troubleshooting

Stop all CLI processes before copying a journal. Copy the entire private directory, including runtime artifacts, to an operator-owned backup outside any Git checkout.

```bash
cp -a -- "$REIVRO_STORE" "$BACKUP_DIRECTORY"
cp -a -- "$BACKUP_DIRECTORY" "$RESTORED_DIRECTORY"
export REIVRO_STORE="$RESTORED_DIRECTORY"
reivro doctor
reivro history "$EVENT"
```

Use fresh destinations and the same OS owner and project. Check directory mode 700 and database mode 600. Cross-user restore requires a separately reviewed ownership migration because journal actor identities are bound to the UID.

A missing runtime manifest can be regenerated with `reivro protect export "$PROTECTION" --private`. Preserve an adulterated file privately before moving it away and re-exporting. Export refuses to overwrite different bytes. Revocation remains in the journal and prevents reactivation by copying a manifest.

A duplicate verification returns inconclusive. Retrieve the persisted result with `history`. If interruption occurred before persistence, retry the same submission. A committed result survives interruption before delivery to the caller.

If doctor reports missing configuration, set the project and private store. If evidence is unavailable, check pinned commits and the trusted checkout. Treat conflict, error, and inconclusion as requiring operator review.

## Real Codex protocol

Use an existing included Codex session only after confirming it has no additional charge. The CLI being installed does not establish the session's entitlement. The founder controls that confirmation.

1. Create a disposable project and approve a contract requiring guide.md at BASE.
2. In the separate agent account's existing Codex session, ask it to change notes.txt and declare completion, deliberately leaving guide.md absent.
3. Import the commit and verify it. Save the independent INCOMPLETE report.
4. Capture criterion 0, confirm the finding, propose and approve the protection.
5. Approve a second task at a new BASE. Ask the same session to repeat the omission.
6. Verify the new HEAD and inspect confirmed recurrence and original evidence.
7. Authorize correction in the operator context. Give the agent only the sanitized report and permission to add guide.md.
8. Verify the corrected commit with --after-correction and save the VERIFIED report.
9. Revoke the protection and confirm it is excluded on the next verification.

Record actual session/client version, task IDs, commit SHAs, event IDs, report digests, human decisions, and failures. Never include session tokens, source content, or credentials. Keep synthetic demonstration results separate from this real-client exercise.

## 90-second demonstration

After installation, run `reivro demo`. Explain that the project and agents are synthetic, then point to incomplete work, confirmed evidence, approved protection, recurrence, authorized correction, and revocation in the output. Run `reivro --json demo` to show machine-readable output if time allows. Measure your recording duration before sharing it. The command completes locally within the measured demo duration, while narration duration remains operator-dependent.

## Feedback Guide

Participation is voluntary. Copy [feedback.json](feedback.json) into a private directory only if you consent to record local measurements. Fill it manually with elapsed times and observations. Leave unavailable values null. Set consent_to_local_recording to true only after deciding to participate.

Record installation time, time to first verification, setup difficulty, report clarity, detected recurrences, correction time, and suspected false positives. Describe the criterion and expected behavior using synthetic examples. Exclude code, paths, credentials, contract objectives, and personal identifiers. Review the file before voluntarily sending it to the founder. REIVRO performs no automatic feedback upload.

## Known Limitations and Founder Checklist

This kit covers local static predicates and local journal recovery. Hosted validation, functional execution, real-client effectiveness, WSL, and a second machine require independent evidence.

Before a private alpha, the founder must validate actual operator/agent account separation, a clean install on a participant machine, source integrity, journal restore, the real Codex protocol under the existing entitlement, and voluntary feedback handling. Review every inconclusive result. Keep the alpha blocked until the account boundary is demonstrated in the intended participant environment.
