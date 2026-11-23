# VERIFY MVP

Check added Python lines in a public GitHub pull request for trailing ASCII spaces or tabs. The rule covers all added physical lines, including blank lines and strings. It checks formatting and does not infer a functional bug or suggest an automatic fix.

```sh
python -B -m server.scop_verify https://github.com/pallets/click/pull/3412 --permission github:read-pr-evidence
python -B -m server.scop_verify https://github.com/pallets/flask/pull/5808 --permission github:read-pr-evidence
```

The CLI uses the existing bounded, read-only GitHub evidence client. It checks file counts, unified diff hunk lengths and addition/deletion totals. It rechecks the head, base and file count before reporting. It does not execute PR code or require credentials, Vercel or Supabase.

Each finding includes the rule, file, head line number, head commit, commit-pinned file link, PR diff anchor and excerpt. JSON preserves trailing whitespace. The report includes up to 100 findings and counts all matches. Long excerpts preserve the last 400 characters and are marked truncated. The PR diff link can change when the branch moves. A head-side file link may require GitHub to retain the commit and file.

| Exit code | Meaning |
| --- | --- |
| 0 | The check completed with no findings within scope. Check coverage counters for PRs without added Python lines. |
| 3 | The check completed and found violations. |
| 2 | Permission or GitHub evidence blocked completion. |
| 1 | Invalid request or execution failure. |
| 130 | Interrupted. |

## Live verification

- Click #3412, head `e6cfbbf0aa9f770db120fac5ab55499711e73395`. Exit 3. 10 Python files, 274 added lines, one finding. Line 9 of `tests/typing/typing_file.py` ends in one space after `import _typeshed as ts`.
- Independent confirmation: GitHub's contents API returned `b'import _typeshed as ts '` on that line at the recorded commit. Running `git -c core.whitespace=blank-at-eol diff --no-index --check /dev/null /tmp/reivro-click-3412.py` against the downloaded file also reported `:9: trailing whitespace.`
- Flask #5808, head `dbd4c2882593f6118103120aa96fa9acdf7deedb`. Exit 0. One Python file, one added line, no findings for this rule.

Live commands inspect the current PR revision. The expected counts apply to the recorded commits. GitHub API rate limits, missing patches or a changed revision can block execution. This is a single CLI check. The existing PR summary and Workspace remain independent entry points.
