# REIVRO Developer Preview V0.1

REIVRO checks operator-approved task criteria against Git commits, records evidence, and applies approved project policies. This preview runs locally in dry run mode. It can report a violation without publishing GitHub Checks or blocking a merge.

## Install and try the demo

Use Linux or WSL with Python 3.10+ and Git available at `/usr/bin/git`. Use a source checkout you control. No package installation, live agent session, service credentials, or paid product is required.

```bash
mkdir -p "$HOME/.local/bin"
ln -s "$REIVRO_SOURCE/reivro" "$HOME/.local/bin/reivro"
export PATH="$HOME/.local/bin:$PATH"
reivro demo
reivro --json demo
```

Set `REIVRO_SOURCE` to the absolute path of the trusted REIVRO clone before installing. Keep that checkout outside agent control. The two demo commands are equivalent output formats. The demo creates a temporary Git repository and journal and deletes them when it exits. It uses synthetic tasks and agent labels with real verification, explicit operator decisions scripted for the demo, and persisted evidence during the run.

## Verify your first task

In an operator-controlled Git checkout with an initial commit, select the project and a dedicated, private journal directory. Its parent must exist and be operator-controlled. Choose a distinct journal for each project.

```bash
export REIVRO_PROJECT=your-org/your-repo
export REIVRO_STORE="$HOME/.reivro-your-repo"
reivro init
reivro doctor
```

From the approved BASE, write `contract.json` outside the checkout. Replace the example project and BASE and generate a fresh UUID for each task. The agent receives the task instructions and a copy of the criteria.

```json
{
  "version": 1,
  "project": "your-org/your-repo",
  "task_id": "180a9261-40c4-4ad3-ac24-dcb3dfba4721",
  "base_sha": "0123456789012345678901234567890123456789",
  "objective": "Add a quickstart.",
  "allowed_paths": ["docs/quickstart.md"],
  "protected_paths": ["README.md"],
  "criteria": [{"kind": "exists", "path": "docs/quickstart.md"}]
}
```

```bash
reivro task approve < contract.json
```

Save the returned `task-…` digest. Ask the agent to commit the work in its separate checkout and return the task ID and candidate HEAD. Import the candidate Git objects into a checkout controlled by the operator without executing candidate scripts, hooks, filters, or tests. Verify that the operator checkout represents the intended HEAD before continuing.

## Submit from Codex, Claude Code, or Cursor

These manual examples work with the same Agent Integration V1 submission format. Give the client the approved task ID and ask it to return its commit SHA. Set `AGENT` to `codex`, `claude-code`, or `cursor` respectively. No client hooks or automatically trusted identity are required. The label is a declaration. Choose the actual PR number when available. For a local-only candidate, `1` is a placeholder required by the message schema and produces no GitHub call.

```bash
python3 -I - "$AGENT" "$REIVRO_PROJECT" "$TASK_ID" "$CANDIDATE_HEAD" > submission.json <<'PY'
import json
import sys
from uuid import uuid4
agent, project, task_id, head_sha = sys.argv[1:]
print(json.dumps(dict(version=1, agent=agent, project=project, task_id=task_id,
                      event_id=str(uuid4()), head_sha=head_sha, pr=1)))
PY
reivro --json verify "$TASK_DIGEST" < submission.json
```

Keep the same event ID for a retry of the same submission. A duplicate returns inconclusive and you can use `reivro history EVENT` to retrieve the original result. Use a fresh event ID for a new revision. Exit status is 0 for a verified result or successful management command, 2 for incomplete work or a policy violation, and 1 for errors or inconclusive verification. Prefix the command with the global option `--json` for structured output, for example `reivro --json history EVENT`.

## Review, protect, and correct

Check the verified BASE and HEAD, the criterion index, and the evidence ID before deciding.

```bash
reivro history "$EVENT"
reivro review capture "$EVENT" --criterion 0
reivro review confirm "$FINDING" --reason "Confirmed the quickstart is missing."
reivro protect propose "$FINDING"
reivro protect approve "$PROTECTION" --reason "Approved as a project-wide requirement."
reivro protect export "$PROTECTION"
reivro status
```

Use `--violation INDEX` to capture a path violation. Use `review reject` to close an invalid finding. Export publishes the digest-bound manifest to the operator checkout for separate versioning. Approval also exports a private runtime copy. Task-specific changes and manual evidence are excluded from automatic promotion.

Preview verification automatically reads the project's approved task policies and compares each private manifest with its journal-approved bytes. Syntax protections continue to use the existing syntax workflow described in [TASK_FIREWALL.md](TASK_FIREWALL.md). A conflict, unavailable artifact, or change to the policy set during verification requires review. A violation in the presence of other unresolved policies is still reported. Resolve simultaneous violations with the operator before granting a correction through the preview. The preview can issue a correction grant when exactly one policy is violated and the rest are clear.

Approve a new task contract from its own BASE. If its submission repeats the same independently observed failure, verify reports the recurrence and links the original evidence. When the operator approves a correction, the agent may submit the corrected commit under the same task.

```bash
reivro authorize-correction "$VIOLATION_EVENT"
reivro verify "$TASK_DIGEST" --after-correction "$VIOLATION_EVENT" < corrected-submission.json
reivro revoke "$PROTECTION" --reason "This project no longer requires the quickstart."
```

## Security, recovery, and removal

- Keep the trusted checkout, CLI, process environment, and journal under a separate OS identity from any agent with shell access. Owner-only permissions alone cannot separate programs running as the same OS user.
- Keep reasons and contract objectives free of credentials. Share the sanitized verification report with the agent and keep approval commands in the operator context.
- A private manifest missing after approval can be regenerated with `reivro protect export "$PROTECTION" --private`. If bytes were altered, retain the damaged file as evidence in private storage, move it out of the runtime path, then re-export. Export refuses to overwrite a different manifest.
- Recover a previously persisted result with `reivro history "$EVENT"`. When taking a backup or restoring the journal and runtime manifests, stop the operator CLI and use the same project and OS owner. Keep the original journal and verify the restore with `reivro doctor`.
- Remove the launcher with `unlink "$HOME/.local/bin/reivro"`. Archive the private journal if its review history is needed. If journal deletion is intended after archiving, remove that specific operator-owned directory locally. Exported manifests should be removed from Git only through the project's normal review process.

Static verification checks pinned commits and supported predicates. Uncommitted changes, semantic task completion, functional execution, and hosted Cloud Memory verification are outside this preview. Manual and hosted-evidence criteria remain inconclusive here. Preview authorization and revocation are local. No third-party client or hosted enforcement was validated in the demo.

An external alpha should validate the clean install on a second operator's machine, a real client handoff without operator-store access, recovery from a preserved journal, and representative project policy conflicts. Measure independently whether participants can complete setup, interpret evidence, and recover failures. Any hosted enforcement needs separate validation and authorization.

## Local validation measurements

The source at `e24ec49` was extracted from Git into a fresh temporary home and launched through the documented symlink with only system Python, Git, and a minimal environment. The measurements exclude downloading the source.

| Measurement | Observed |
| --- | ---: |
| Create the launcher and run `--help` | 507.937 ms |
| Create and initialize the demo project, median of five | 45.298 ms |
| Time through the first demo verification, median of five | 102.761 ms |
| Verification operations inside the demo, median of 20 | 26.886 ms |
| Slowest of those 20 verification operations | 35.438 ms |
| Demo runs completed | 5 of 5 |
| REIVRO commands through first verification | 3 required, plus optional `doctor` |
| Demo steps | 13 per run |
| Missing project or journal configuration | Exit 1 with instructions |

The demo executes the CLI dispatcher in one process. These measurements exclude human review, agent turnaround, repository import, and repeated process startup. They describe one environment and one synthetic workload.
