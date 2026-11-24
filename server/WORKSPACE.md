# Workspace integration v0.6

The Workspace boundary consumes one UTF-8 JSON request and returns one structured workflow result. It invokes [REIVRO Workflow v0.5](WORKFLOW.md) in-process, preserving its Core skill selection, summary generation, evidence checks, and execution records.

## Local example

Use Python 3.12 from a trusted REIVRO checkout. Ask the caller to approve read-only access to public GitHub PR metadata and diffs before including the permission. Omitting the permission blocks external access.

```sh
python -B -m server.scop_workspace <<'JSON'
{"pr_url":"https://github.com/pallets/flask/pull/5808","permissions":["github:read-pr-evidence"]}
JSON
```

Python callers can invoke `handle_request(binary_stream)` in `server.scop_workspace` and receive the same response as a dataclass plus its exit code. There is no HTTP listener, CORS setting, authentication layer, or shared persistence.

## Contract

| Request field | Type | Meaning |
| --- | --- | --- |
| `pr_url` | String | Required canonical public GitHub PR URL. |
| `permissions` | Array of strings | Defaults to empty. The workflow requires exactly `["github:read-pr-evidence"]`. |
| `task` | String | Optional Core task description. Defaults to the PR-summary task. Skills without adapters report `unsupported_skill`. |

Requests have a 32 KiB limit. Unknown fields, duplicate keys, invalid UTF-8, and malformed JSON are rejected. The workflow checks URL, task, and permission semantics before external access.

Every response includes `contract_version: "0.6"`, `execution`, and `request_error`. Transport or decoding errors have a null `execution` and a request error with a code and message. Workflow results include the execution ID, status, selected skill, steps and durations, error code and message, limitations, summary, and evidence reference counts. An unsuccessful required verification leaves the summary null. Exit codes are 0 for completed, 1 for failed or invalid transport input, 2 for blocked, and 130 for cancelled.

## Integration and security limits

A Workspace client should render status and duration from the execution record, show each step, and associate citation links with their corresponding matched excerpts. Display untrusted PR prose and diff content as text or sanitize it before rendering. A matched citation establishes that the excerpt occurred in the fetched evidence. Semantic correctness requires review.

The local process assumes a trusted checkout and caller. The permission field is an explicit action grant for this local contract. An eventual network service would require authenticated caller identity, server-owned authorization, resource controls, and an origin policy. The boundary inherits the workflow's [network and evidence limits](WORKFLOW.md). It does not issue repository writes or execute PR content.

## Design dependency

No approved Claude Workspace design or official MVP PRD was available in the checked repository, supplied files, or linked GitHub project records. This delivery uses the non-visual integration path. Implement the frontend only after those sources are available so its layout, navigation, terminology, and interactions can be verified.

## Test

```sh
python -m pytest -q
SCOP_LIVE_TESTS=1 python -m pytest -q
```

## Local web client (v0.8)

[Functional Workspace](WEB.md) now provides a loopback-only browser interface for this unchanged contract and optional v0.7 measurement recording. The earlier design-dependency note describes the v0.6 delivery context. The user subsequently clarified that conceptual vision and requirements are available, with no finalized visual design; v0.8 implements a minimal interface on that basis.
