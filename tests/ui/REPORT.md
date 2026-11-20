# Workspace v0.8 validation

Base: main `66b6637` (merged Measurement PR #11). Local Python 3.12.14, pytest 8.4.2; Playwright 1.58.2 with installed `/usr/bin/chromium`. No production runtime dependencies added.

## Executed checks

| Command | Actual result | Exit |
| --- | --- | --- |
| `python -m pytest -q` | 87 passed, 5 live checks skipped | 0 |
| `SCOP_LIVE_TESTS=1 python -m pytest -q` | 92 passed (14.40 seconds) | 0 |
| `PYTHON=/tmp/scop-pytest.k2zZxC/bin/python SCOP_CHROMIUM=/usr/bin/chromium node --test tests/ui/workspace.test.cjs` | 5 passed, 0 failed (7.53 seconds) | 0 |
| `PYTHON=/tmp/scop-pytest.k2zZxC/bin/python SCOP_CHROMIUM=/usr/bin/chromium SCOP_UI_LIVE=1 node --test tests/ui/workspace.test.cjs` | 3 passed, 2 fixture-only tests skipped, 0 failed (6.84 seconds) | 0 |
| `node --check web/app.js` and `git diff --check` | Passed | 0 |
| PyYAML parse of `.github/workflows/scop-tests.yml` | Parsed; contents read-only; six steps confirmed | 0 |

Python commands used `/tmp/scop-pytest.k2zZxC/bin/python`, with `PYTHONDONTWRITEBYTECODE=1` and `PYTEST_ADDOPTS='-p no:cacheprovider'`. These avoid disposable cache writes and do not change test selection. See [setup and portable commands](../../server/WEB.md).

The initial browser launch failed because the preinstalled Playwright lacked its bundled Chromium. Using `SCOP_CHROMIUM=/usr/bin/chromium` resolved it. The pinned test dependency was then installed using `npm install --ignore-scripts --cache /tmp/scop-npm-cache --prefix tests/ui`; all final browser results above used Playwright 1.58.2. CI installs its matching Chromium separately.

## Real browser execution

Input: https://github.com/pallets/flask/pull/5808

- Execution: `b6cce51e-d672-4dd4-bd2d-a2d49e568512`.
- Technical result: completed, skill `pr-source-summary`.
- Workflow duration: 1134.425 ms; request validation 8.832 ms, selection 0.933 ms, generation 1118.641 ms, verification 5.714 ms.
- Four of four citations matched: merged=true, author description, removal of `def select_jinja_autoescape(self, filename: str) -> bool:`, and addition of `def select_jinja_autoescape(self, filename: str | None) -> bool:` in `src/flask/sansio/app.py`.
- Rendered links and full prefixed excerpts came from the actual backend response. The browser submitted an automated Accepted decision to a disposable store to test feedback persistence; this is **test input, not human quality approval**. Missing human times remained unknown; total time remained partial; completion rate remained unknown.
- Screenshot before automated feedback: `/tmp/scop-workspace-live-unreviewed.png`. The test also checks a 390px mobile viewport for horizontal overflow.

Offline browser tests execute the real Python workflow against substituted upstream responses. They cover permission denial, invalid URL, unavailable GitHub, failed excerpt verification, actual KeyboardInterrupt handling, untrusted HTML rendered literally, forbidden link schemes/hosts, keyboard focus, no implicit external browser requests, feedback and missing values. The live mode skips only unavailable-source and mismatch/interruption fixture tests.

HTTP tests additionally cover malformed/oversized/invalid-encoding input, cross-origin/Host/token rejection, denied local writes, successful unrecorded execution without store writes, duplicate feedback, unknown metrics, busy responses, CSP/no CORS, redacted unexpected exceptions, and live public PR execution. Existing skill, Core, runtime, workflow, Workspace and measurement tests remain unchanged.

## Limits

This evidence supports a local functional MVP only. No multi-user deployment, hard cancellation, streaming progress, durable summary history, idempotent retries, semantic-verification guarantee, or measured productivity gains are claimed. Browser checks are Chromium-based, not a full assistive-technology or cross-browser audit. GitHub API availability/rate limits remain external dependencies. Hosted CI status is reported in the PR and delivery report after the push.

## Hosted CI runner correction

The first hosted run passed Python (87 passed, 5 skipped) but browser installation failed: `ubuntu-latest` resolved to Ubuntu 26.04, unsupported by pinned Playwright 1.58.2. The workflow now pins `ubuntu-24.04`, a supported runner, rather than weakening or skipping browser checks. The final hosted result is linked in the PR delivery report.
