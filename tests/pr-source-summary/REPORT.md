# PR source summary validation

Checked on 2026-11-18 UTC. All three public PRs were accessible. Each summary was drafted from GitHub metadata and diffs, then checked against the cited evidence. The pytest regression and Flask autoescape behavior were attributed to the respective PR authors where the record relied on the PR description.

| PR | Structure and reference format | Live evidence | References checked |
| --- | --- | --- | --- |
| [pallets/flask #5898](https://github.com/pallets/flask/pull/5898) | Pass | Pass | 5 |
| [pallets/flask #5808](https://github.com/pallets/flask/pull/5808) | Pass | Pass | 3 |
| [pytest-dev/pytest #12022](https://github.com/pytest-dev/pytest/pull/12022) | Pass | Pass | 6 |

## Reproduce

Run from the SCOP repository root with Python 3. Live mode requires read access to the public GitHub REST API.

```sh
python -B tests/pr-source-summary/validate.py
python -B tests/pr-source-summary/validate.py --live
python -B -m unittest discover -s tests/pr-source-summary -p 'test_*.py' -v
```

Both runs exited 0 with **3 passed, 0 blocked, 0 failed**. Live mode checked all 14 excerpts against GitHub PR metadata, descriptions, or file patches. The regression suite exited 0 with **13 passed, 0 failed**. It uses local fixtures and mocked GitHub responses. Negative tests assert rejection of missing or incorrect diff prefixes, partial lines, file headers, excerpts that span hunks, missing or duplicate records, unexpected PR identities, incorrect references, and missing fields. Positive tests cover complete changed and context lines, evidence after a no-newline marker, and valid records under alternate filenames.

The existing pytest #12022 changelog excerpt was extended to the full line returned by GitHub so it meets the stricter matching rule. All three records retain their original claims and source links.

The validator checks source URLs and excerpts. Claim interpretation was reviewed manually. Upstream test suites and CI results were outside this validation run.
