# REIVRO Workflow Integration v0.5

Generate a reviewable summary from a public PR URL using the existing Core selector, PR Summary generator, schema validator, and GitHub evidence matcher. The workflow returns a UUID, overall status, duration in milliseconds, lifecycle events, step records, and the verified summary with citation counts.

```sh
python -B -m server.scop_workflow https://github.com/pallets/flask/pull/5808 \
  --permission github:read-pr-evidence
```

Run from a trusted REIVRO checkout with Python 3.12. The permission is opt-in and must be the only grant. The CLI uses unauthenticated GETs to the fixed GitHub API. It refuses redirects and never executes PR content, modifies repositories, or merges PRs.

| Step | Requires | Action |
| --- | --- | --- |
| `validate_request` | — | Check the permission, canonical URL, and task length. |
| `select_skill` | `validate_request` | Use Core's unique highest-ranked installed skill. |
| `generate_summary` | `select_skill` | Run the v0.4 draft stage with the existing bounded GitHub adapter. |
| `verify_evidence` | `generate_summary` | Validate the record and compare each citation to the fetched evidence. Publish the summary only after both checks succeed. |

Workflow exits are 0 for `completed`, 1 for `failed`, 2 for `blocked`, and 130 for `cancelled`. Unstarted steps remain `queued` with a null duration. A terminal error stops the chain, and a failed verification keeps partial comparison counts while withholding the summary. The `--task` option exercises Core selection. Regression Test Generator is discoverable and returns `unsupported_skill` because it has no workflow adapter.

Future integrations can add a trusted adapter at the selection boundary and declare the stages it requires. Skill Markdown supplies discovery metadata. It cannot register commands or grant permissions.

The workflow inherits the [v0.4 evidence limits](PR_SUMMARY.md). Public API rate limits and missing patches can block execution. Network responses are collected sequentially, and DNS or headers can overrun the time budget. Citation matching leaves claim interpretation to the reviewer. Results and timings are per run and are written to stdout.

```sh
python -m pytest -q
SCOP_LIVE_TESTS=1 python -m pytest -q
```

The optional public GitHub test runs the CLI with a write and process-launch audit guard. Keep live tests opt-in so the required offline CI job remains independent of GitHub API availability.
