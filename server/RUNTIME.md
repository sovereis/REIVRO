# REIVRO Runtime v0.2

The first workflow audits one existing PR-summary JSON record. It checks the record against the existing Pull Request Summary validator and reports the number of claims and source references checked. Run it before handing a summary to a reviewer.

## Run an audit

From the REIVRO repository root, with Python 3.12, run:

```sh
python -B -m server.scop_runtime "audit a GitHub pull request summary" \
  < tests/pr-source-summary/pallets-flask-5808.json
```

The example returns `completed`, the PR URL, three claims, three references, time in milliseconds, and the three source references. When validation starts, the result records `tests/pr-source-summary/validate.py::validate` and `validation_mode: offline_structure`. Both fields are null when the validator is never invoked. Those counts describe the record's coverage. They do not measure time saved or establish the truth of the claims.

The CLI reads one UTF-8 JSON object of up to 256,000 bytes on stdin and writes one JSON result on stdout. `-B` prevents Python bytecode writes. The optional repeatable `--permission` flag replaces the default grant. Only `local:read-summary-record` is supported. No repository write, GitHub access, model call, or subprocess is part of the audit.

| Result status | Exit code | Meaning |
| --- | ---: | --- |
| `completed` | 0 | The record passed the structure and reference-format checks. |
| `failed` | 1 | Input, dependency, or execution error. |
| `blocked` | 2 | Permission denied, no supported unambiguous match, or the supplied record reports a blocker. |
| `cancelled` | 130 | An interrupt was caught while processing the task. |

Argument parsing errors are reported separately by the CLI on stderr. Task results record `queued` on receipt and `running` when the adapter begins. The final log entry records the terminal state and elapsed time. This is a synchronous process with in-memory logs and no persistent queue. Input bytes and task length are capped. The runtime has no wall-clock timeout and may wait for stdin to close.

## Execution boundary

The Python API accepts a `TaskRequest` and a binary input stream. It checks permissions before discovery or input reads. Core ranks installed skill metadata using lexical matching. Only a unique top match for Pull Request Summary can reach the hard-coded adapter. The adapter calls the existing validator's per-record function from the trusted REIVRO checkout. The Markdown definition and supplied record are data. Neither can select a command, validator path, network endpoint, or permission.

The policy controls what this runtime invokes. It does not sandbox Python or an installation whose source files are writable by untrusted actors. Use a trusted REIVRO checkout. Task input and command-line arguments are supplied by the local caller.

## Verify

```sh
python -m pytest -q
```

Only the test runner requires pytest. The runtime uses the standard library. The end-to-end test launches the CLI in a temporary directory with the checked-in Flask record, checks the measured result and evidence references, and verifies that a changed source URL produces an actual validation failure.

## Remaining MVP work

Add a read-only GitHub evidence adapter and a workflow that produces a fresh summary from a PR, with explicit consent, bounded requests, and independently verified citations. Validate the workflow with developers and measure delivery time and reviewer corrections against their existing process. The current audit validates one record and leaves live evidence checking and claim interpretation to a separate review.
