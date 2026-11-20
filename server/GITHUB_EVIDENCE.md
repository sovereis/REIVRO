# SCOP GitHub Evidence Adapter v0.3 — proposed PR #7

This optional workflow checks **an existing PR-summary record** against GitHub's current PR metadata, body and diff. It does not generate a new summary or prove that the natural-language claims are semantically correct.

## Usage

From a trusted repository checkout, for a public PR:

```sh
python -B -m server.scop_github_evidence "audit a GitHub pull request summary" \
  --permission github:read-pr-evidence \
  < tests/pr-source-summary/pallets-flask-5808.json
```

The adapter first executes the existing offline structural audit. Only if it passes does the adapter request GitHub data and compare every cited excerpt with the corresponding metadata, description or actual diff hunk. It reports `references_checked` and `references_verified`, a duration, lifecycle events, and an explicit `github_live_evidence` mode.

**No implicit network permission:** omitting `--permission github:read-pr-evidence` blocks the request *before reading stdin*. Other/extra permissions also block execution. No GitHub token, repo writes, subprocess calls, user-provided endpoints, or summary generation are supported.

## Security and limitations

- Public GitHub PRs only; unauthenticated requests are rate-limited.
- GitHub API origin is fixed in the adapter; PR identity is validated by the existing offline validator.
- Requests have a 10-second network timeout, redirect following disabled, and a 2 MB limit per response.
- Diff file enumeration is limited to three pages of 100 files. If required files/patches are inaccessible, the result is `blocked` rather than falsely `completed`.
- An excerpt mismatch is `failed`; source unavailability is `blocked`.
- Existing offline validator and skill definitions are unchanged.
- Local input remains limited to 256 KB. CLI stdin itself can still wait without a wall-clock timeout.
- Evidence matching confirms quoted text/patch lines from GitHub; it does **not** verify all semantic interpretations, security implications, runtime behavior, or productivity gains.
- The runtime relies on a trusted Python checkout and is not an OS sandbox.

## Validate

```sh
python -m pytest -q
python -m pytest -q tests/test_scop_github_evidence.py
```

The tests mock only the HTTP evidence responses, exercising the real existing offline validation, runtime and diff matcher. A separately observed live GitHub run is still required before declaring the milestone fully verified.

## Next work

Generate a fresh source-grounded summary directly from a PR; preserve evidence references and measure reviewer corrections and total time to accepted output.
