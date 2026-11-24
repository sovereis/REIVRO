# Automated PR Summary v0.4

Generate and verify a summary from a canonical public GitHub PR URL. The command reads GitHub metadata, the author description, and changed-file patches. It emits JSON with the summary, reference counts, lifecycle events, duration, and any error.

```sh
python -B -m server.scop_pr_summary https://github.com/pallets/flask/pull/5808 \
  --permission github:read-pr-evidence
```

Without the exact permission grant, the command exits 2 before contacting GitHub. Use a trusted REIVRO checkout. The CLI issues unauthenticated GETs to the fixed GitHub API with redirects disabled. It does not execute PR content or write to the repository.

## Evidence and coverage

The generator reports observed merge status and up to five representative file changes ordered by changed line count. It quotes author motivation when it recognizes an explicit label such as “Why” and otherwise attributes any selected prose as description context. It makes no inferred claims. It validates the generated record against the existing Pull Request Summary schema and checks each citation against the fetched responses. Exit 0 means those checks passed. Exit 1 indicates invalid input, a record or evidence mismatch, or an internal failure. Exit 2 indicates denied access or unavailable evidence. An interrupt exits 130.

The adapter shares the existing response caps of 2 MB per response and up to three file pages. Socket timeouts are at most 10 seconds. The 30-second budget is checked between requests and body reads. It is not a hard wall-clock deadline for DNS or header processing. Unauthenticated requests can be rate-limited. Missing patches, line-count discrepancies, and incomplete file listings block generation. Binary or rename-only changes without textual patches can therefore block a summary. The API responses are read sequentially and can change during a run. Exact excerpt matching checks citation text; reviewers still assess representativeness, author intent, and factual implications.

## Verification

```sh
python -m pytest -q
SCOP_LIVE_TESTS=1 python -m pytest -q tests/test_scop_pr_summary.py
```

The first command is the offline CI gate. The opt-in test calls the real CLI against the public Flask PR shown above and needs access to GitHub's public API.
