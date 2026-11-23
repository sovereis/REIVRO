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

## Python syntax regression check

Select the syntax rule explicitly. The default whitespace rule retains its original output and exit codes.

```sh
python -B -m server.scop_verify https://github.com/pallets/flask/pull/5808 \
  --permission github:read-pr-evidence --rule python-syntax-regression
```

The rule fetches both files through the GitHub Contents API using the PR's literal BASE and HEAD SHAs. It validates the response path, size, Base64 encoding and Git blob hash, and checks the HEAD blob against the PR file record. It aligns the full patch with both snapshots, then rechecks the PR revisions and file count before reporting. A PR diff calculated from a different merge base may fail alignment and yield an inconclusive result. HEAD and BASE file URLs are pinned to commits. The parent trusts GitHub to resolve the Contents request for the specified SHA.

A regression requires a compilable BASE and a HEAD syntax diagnostic on a single added line whose text did not already occur in BASE. Diagnostic location is intentionally conservative. A syntax error explained by a deletion, spanning multiple lines, or reported on an unchanged or repeated line can remain inconclusive. New and removed files are inconclusive because they lack a pair. Python-to-Python renames use the previous path in BASE and the current path in HEAD. Cross-extension renames are inconclusive.

| Status | Exit | Meaning |
| --- | --- | --- |
| `REGRESSION_DETECTED` | 3 | At least one regression was confirmed. The per-file results show any remaining gaps. |
| `ERROR` | 1 | Invalid request, infrastructure or compiler failure, with no confirmed regression. |
| `INCONCLUSIVE` | 2 | Missing permission, evidence or comparable input, with no confirmed regression. |
| `PASS` | 0 | Every file in scope passed with the reported CPython version. |

The compiler requires Linux, CPython and the system `libseccomp.so.2`. Each subprocess starts in an empty temporary directory with an empty environment, a pipe for input, a temporary result file and no inherited extra descriptors. It sets resource limits and activates a syscall allowlist before reading the source. Socket creation, file opens and process creation are denied. The worker calls `compile()` in memory and discards the code object. The parent does not fall back to unsandboxed compilation if setup fails. The isolation still relies on the local interpreter, system library and Linux kernel. The repository targets CPython 3.12 on Linux. Results reflect the reported interpreter version and grammar, which may differ from the PR project’s target Python version. Source evidence supports UTF-8 and ASCII with LF or CRLF line endings.

Limits are 12 changed Python files, 128 KiB per source, up to 29 logical GitHub requests under the existing response and network limits, two seconds of wall time and one second of CPU time per compiler process, 128 MiB of address space per process, and 4 KiB of worker output. The verification shares a 30-second deadline across network and compilation.

### Reproduce a regression

Run the controlled fixture with a real compiler and recorded GitHub response shapes. It checks `x = 1` in BASE and `x = )` in HEAD and confirms the reported line and SHA links. The fixture PR and commit IDs are synthetic.

```sh
python -m pytest -q tests/test_scop_verify_syntax.py::test_syntax_cli_reports_finding_and_exit_code
```
