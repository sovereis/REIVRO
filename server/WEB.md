# Functional Workspace

A local web interface for the existing PR summary workflow and measurement contracts. The official MVP PRD informed the separation between technical completion and human acceptance, permissions, evidence, and missing metrics. There is no approved pixel-perfect design or implemented Claude frontend; this is a minimal functional interface, not a claim of design conformance or completion of every PRD requirement.

## Start

For first-time setup on Windows with WSL or Linux, see the [quick start](../README.md).

From the trusted checkout on Linux, using Python 3.12:

```sh
python -B -m server.scop_web
# Open http://127.0.0.1:8765
```

No runtime packages, frontend build, GitHub token, or secrets are required. For optional recording, first create a dedicated private directory **outside all Git worktrees**:

```sh
store=$(mktemp -d /tmp/scop-web-measurements.XXXXXX)
python -B -m server.scop_web --store-dir "$store" --port 8765
```

The server does not create the store. Choose a durable owner-only location if measurements should survive temporary-directory cleanup. Do not reuse an experiment dataset for automated UI tests. Shutdown is Ctrl+C.

1. Enter a canonical public GitHub PR URL and authorize read-only GitHub access.
2. Optionally authorize measurement recording, then generate the summary.
3. Review actual steps, duration, claims, exact excerpts, links, and limitations.
4. For a recorded, completed run, submit Accepted or Needs Rework with explicit local-write consent. Optional times are seconds converted to integer milliseconds, with human-measured or human-reported provenance. Blank means unknown, not zero.
5. Load local measurements to see de-identified observations and ratios. Unreviewed observations remain unreviewed. Completion rate stays unknown because the UI does not attest cohort completeness.

## Architecture and contracts

`web/index.html`, `style.css`, and `app.js` use semantic HTML, responsive CSS and browser DOM APIs without a framework. `server.scop_web` serves only three fixed assets and two POST routes. No path or command is constructed from PR content.

- `/api/run`: `{request: <unchanged v0.6 request>, record_measurement: boolean, permissions: []}`. Without recording, calls Workspace directly. With recording, requires `["local:write-measurements"]` and delegates to v0.7 `run`, which invokes v0.6 itself. Nested GitHub permission is independently enforced by the workflow.
- `/api/measurement`: accepts v0.7 `get`, `export`, and `feedback` requests. Feedback requires its own local-write grant. No import, arbitrary file, shell, or caller-supplied execution route exists.
- HTTP 200 means a contract response was returned; inspect its error and workflow status. Transport/origin errors use HTTP 4xx/5xx. A transport failure leaves outcome unknown, never implicitly successful.

The browser shows a waiting state until the synchronous workflow returns. Final steps and lifecycle status come from the execution record. It renders completed, failed, blocked, or cancelled records; there is **no Cancel button**, streaming progress, automatic retry, or fabricated intermediate step completion. Closing/reloading a page cannot cancel execution. The current workflow cannot reliably terminate an in-flight network request.

The v0.6/v0.7 modules and both skills/validators are unchanged. Regression Test Generator has no executable adapter. New workflows must first have a trusted backend adapter with its own permission and evidence checks.

## Security boundary

Single-user local development tool, not a production HTTP service. Listener is hardcoded to IPv4 loopback. Use the exact printed `127.0.0.1` origin. Host allowlisting resists DNS rebinding; POSTs require exact Origin and an unpredictable per-process session token obtained from the same-origin page. Cross-site fetch metadata is rejected, CORS is not enabled, and framing is denied. A local process able to read the page can obtain the token; this does not isolate hostile OS users, browser extensions, or compromised same-origin code. Never expose through a proxy/tunnel or port-forward to untrusted users.

All PR content is rendered through `textContent`, never HTML/Markdown execution. Citation links allow only HTTPS GitHub/API hosts, without credentials. CSP limits scripts/styles/connections to self; no inline code, third-party resources, eval, or telemetry. Errors redact unexpected exception details; HTTP request logging is disabled. Browser traffic to GitHub occurs only when the user follows an evidence link; workflow GitHub reads happen server-side after permission checks.

HTTP bodies are capped at 64 KiB with strict JSON decoding, bounded headers inherited from Python's parser, ten-second socket inactivity timeout, eight active connections and one contract operation at a time. Concurrent operations receive 409 without retry. Existing bounded GitHub responses, pagination, and network budgets are preserved. DNS/header waits can exceed the inherited budget; no hard wall-clock execution isolation is claimed. Slow local clients can monopolize limited slots; not a hardened multi-user server.

Measurement permissions and the existing descriptor-relative, no-symlink, owner-only store apply unchanged. Summary content exists in browser memory and response only; refresh loses it. Measurement rows persist when authorized, but cannot reconstruct full summaries. Same OS user can change the local records; storage is not tamper-proof. Repeated explicit runs create separate executions; no idempotency key or lost-response recovery exists. Citation matching does not establish semantic correctness, productivity gains, cost, or time saved.

## Tests

Test-only dependencies: pytest 8.4.2, Node.js (22+), Playwright 1.58.2 and Chromium. Runtime does not need Node. The lockfile pins browser-test dependencies; installs disable npm lifecycle scripts.

```sh
python -m pip install pytest==8.4.2
python -m pytest -q
npm ci --ignore-scripts --prefix tests/ui
tests/ui/node_modules/.bin/playwright install --with-deps chromium
node --test tests/ui/workspace.test.cjs

# Explicit public GitHub opt-in; API rate limits can block these checks.
SCOP_LIVE_TESTS=1 python -m pytest -q
SCOP_UI_LIVE=1 node --test tests/ui/workspace.test.cjs
```

Use `PYTHON=/path/to/venv/bin/python` for the UI server and `SCOP_CHROMIUM=/path/to/chromium` to use an installed browser. Run commands at repository root. The offline browser suite substitutes only GitHub responses, executes real Core/workflow/schema/evidence logic, and uses disposable stores. The live suite fetches Flask #5808 without substituted evidence. Its automated Accepted submission tests persistence only and **is not an actual human evaluation or productivity observation**. Live tests skip fixture-only unavailable/mismatch/interruption cases, which run in the offline suite.

Screenshots are written outside the repository: `/tmp/scop-workspace.png` (test evaluation), plus `/tmp/scop-workspace-live-unreviewed.png` for the live result before automated feedback. Override the general screenshot with `SCOP_SCREENSHOT`. Required GitHub Actions runs Python and offline browser suites; live checks remain opt-in.
