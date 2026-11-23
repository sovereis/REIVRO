"""Pinned GitHub fixtures exercise the actual isolated CPython compiler."""
import base64
from hashlib import sha1
from pathlib import Path
import subprocess
import sys
from time import monotonic
from urllib.error import HTTPError

import pytest

from server import scop_verify_syntax as syntax

PR = "https://github.com/example/project/pull/12"
API = "https://api.github.com/repos/example/project"
PULL = f"{API}/pulls/12"
PATH = "src/check.py"
BASE, HEAD = "a" * 40, "b" * 40
PERMISSION = (syntax.github.GITHUB_READ,)


def source(path, data):
    blob = sha1(b"blob " + str(len(data)).encode() + b"\0" + data, usedforsecurity=False)
    return {"path": path, "type": "file", "encoding": "base64", "size": len(data),
            "sha": blob.hexdigest(), "content": base64.b64encode(data).decode()}


@pytest.fixture
def install(monkeypatch):
    def install_case(before=b"x = 1\n", after=b"x = )\n",
                     patch="@@ -1 +1 @@\n-x = 1\n+x = )", status="modified", previous=PATH):
        metadata = {"html_url": PR, "head": {"sha": HEAD}, "base": {"sha": BASE}, "changed_files": 1}
        old, new = source(previous, before), source(PATH, after)
        item = {"filename": PATH, "status": status, "previous_filename": previous,
                "sha": new["sha"], "patch": patch, "additions": 1, "deletions": 1}
        responses = {
            PULL: metadata, f"{PULL}/files?per_page=100&page=1": [item],
            f"{API}/contents/{previous}?ref={BASE}": old,
            f"{API}/contents/{PATH}?ref={HEAD}": new,
        }
        calls = []

        def fetch(url, deadline):
            calls.append(url)
            result = responses[url]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(syntax.github, "fetch_json", fetch)
        return responses, calls

    return install_case


def test_introduced_regression_has_pinned_evidence(install):
    _, calls = install()
    report = syntax.verify_syntax(PR, PERMISSION)
    assert report["status"] == "REGRESSION_DETECTED", report
    assert (report["repository"], report["pr"], report["base_sha"], report["head_sha"]) == (
        "example/project", 12, BASE, HEAD)
    finding, = report["files"]
    assert (finding["rule"], finding["file"], finding["line"]) == (syntax.RULE, PATH, 1)
    assert (finding["exception"], finding["diagnostic"], finding["excerpt"]) == (
        "SyntaxError", "unmatched ')'", "+x = )")
    assert finding["base_file_url"].endswith(f"/blob/{BASE}/{PATH}")
    assert finding["head_file_url"].endswith(f"/blob/{HEAD}/{PATH}#L1")
    assert calls.count(PULL) == 2


def test_both_valid_without_executing_source(install, tmp_path):
    marker = tmp_path / "execution-marker"
    code = f"open({str(marker)!r}, 'w').close()"
    install(after=(code + "\n").encode(), patch=f"@@ -1 +1 @@\n-x = 1\n+{code}")
    assert syntax.verify_syntax(PR, PERMISSION)["status"] == "PASS"
    assert not marker.exists()


def test_base_already_invalid(install):
    install(before=b"x = (\n", patch="@@ -1 +1 @@\n-x = (\n+x = )")
    assert syntax.verify_syntax(PR, PERMISSION)["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize("missing", ["patch", "blob", "file", "integrity", "size", "wrong_base"])
def test_missing_or_inconsistent_evidence(install, missing):
    responses, _ = install()
    entry = responses[f"{PULL}/files?per_page=100&page=1"][0]
    target = f"{API}/contents/{PATH}?ref={HEAD}"
    if missing in {"patch", "blob"}:
        entry.pop("patch" if missing == "patch" else "sha")
    elif missing == "file":
        try:
            raise HTTPError(target, 404, "Not found", None, None)
        except HTTPError as cause:
            error = syntax.github._Unavailable("Request failed")
            error.__cause__ = cause
            responses[target] = error
    elif missing == "wrong_base":
        responses[f"{API}/contents/{PATH}?ref={BASE}"] = source(PATH, b"x = 42\n")
    elif missing == "size":
        responses[target]["size"] = syntax.MAX_SOURCE + 1
    else:
        responses[target]["content"] = base64.b64encode(b"x = (\n").decode()
    assert syntax.verify_syntax(PR, PERMISSION)["status"] == "INCONCLUSIVE"


def test_ambiguous_diagnostic_on_unchanged_line(install):
    responses, _ = install(before=b"if True:\n    x = 1\n", after=b"if True:\n",
            patch="@@ -1,2 +1 @@\n if True:\n-    x = 1")
    responses[f"{PULL}/files?per_page=100&page=1"][0]["additions"] = 0
    report = syntax.verify_syntax(PR, PERMISSION)
    assert report["status"] == "INCONCLUSIVE"
    assert "attributed" in report["files"][0]["reason"]


def test_revision_change_discards_tentative_result(install, monkeypatch):
    responses, _ = install()
    original = syntax.github.fetch_json
    meta = iter([responses[PULL], {**responses[PULL], "head": {"sha": "c" * 40}}])
    monkeypatch.setattr(syntax.github, "fetch_json",
                        lambda url, deadline: next(meta) if url == PULL else original(url, deadline))
    report = syntax.verify_syntax(PR, PERMISSION)
    assert report["status"] == "INCONCLUSIVE" and report["files"] == []


def test_github_access_error_and_missing_permission(install):
    responses, calls = install()
    responses[PULL] = syntax.github._Unavailable("GitHub evidence could not be retrieved")
    assert syntax.verify_syntax(PR)["status"] == "INCONCLUSIVE"
    assert not calls
    assert syntax.verify_syntax(PR, PERMISSION)["status"] == "ERROR"


def test_timeout_is_operational_error(install, monkeypatch):
    install()

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(syntax.subprocess, "run", timeout)
    report = syntax.verify_syntax(PR, PERMISSION)
    assert report["status"] == "ERROR"
    assert report["files"][0]["reason"] == "Compiler timed out"


@pytest.mark.parametrize("status", ["added", "removed"])
def test_added_and_removed_have_no_baseline_pair(install, status):
    _, calls = install(status=status)
    assert syntax.verify_syntax(PR, PERMISSION)["status"] == "INCONCLUSIVE"
    assert not any("/contents/" in call for call in calls)


def test_rename_uses_previous_path_for_base(install):
    _, calls = install(status="renamed", previous="src/old.py")
    assert syntax.verify_syntax(PR, PERMISSION)["status"] == "REGRESSION_DETECTED"
    assert f"{API}/contents/src/old.py?ref={BASE}" in calls


def test_worker_denies_network_and_file_open(tmp_path):
    worker = Path(syntax._WORKER)
    for operation in ("socket.socket()", "open('/etc/passwd')"):
        probe = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c",
             f"import runpy, socket; runpy.run_path({str(worker)!r})['restrict'](); {operation}; print('allowed')"],
            cwd=tmp_path, env={}, capture_output=True, timeout=2, check=False,
        )
        assert probe.returncode != 0 and not probe.stdout
        assert b'PermissionError' in probe.stderr


def test_syntax_flag_does_not_change_default_whitespace_cli(install, capsys, monkeypatch):
    from server import scop_verify

    install(after=b"x = 1 \n", patch="@@ -1 +1 @@\n-x = 1\n+x = 1 ")
    monkeypatch.setattr(sys, "argv", ["verify", PR, "--permission", PERMISSION[0]])
    assert scop_verify.main() == 3
    assert '"rule": "python-trailing-whitespace"' in capsys.readouterr().out


def test_real_worker_compiles_in_memory():
    assert syntax._compile(b"x = 1\n", monotonic() + 3) == {"kind": "valid"}


def test_syntax_cli_reports_finding_and_exit_code(install, capsys, monkeypatch):
    import json

    from server import scop_verify

    install()
    monkeypatch.setattr(sys, "argv", ["verify", PR, "--rule", syntax.RULE, "--permission", PERMISSION[0]])
    assert scop_verify.main() == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "REGRESSION_DETECTED"
    assert result["files"][0]["excerpt"] == "+x = )"


def test_worker_failure_has_no_unsafe_fallback(install, monkeypatch):
    install()
    monkeypatch.setattr(syntax.subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess(a[0], 1, stdout=b""))
    report = syntax.verify_syntax(PR, PERMISSION)
    assert report["status"] == "ERROR"
    assert "sandbox" in report["files"][0]["reason"]


def test_missing_newline_requires_matching_patch_marker(install):
    install(after=b"x = )")
    assert syntax.verify_syntax(PR, PERMISSION)["status"] == "INCONCLUSIVE"
    install(after=b"x = )", patch="@@ -1 +1 @@\n-x = 1\n+x = )\n\\ No newline at end of file")
    assert syntax.verify_syntax(PR, PERMISSION)["status"] == "REGRESSION_DETECTED"


@pytest.mark.parametrize("path", ["../check.py", "%2E%2E/check.py", "src%2Fcheck.py", "src%00.py"])
def test_contents_boundary_rejects_ambiguous_paths(path):
    with pytest.raises(syntax.github._Unavailable, match="unsupported evidence endpoint"):
        syntax.github.fetch_json(f"{API}/contents/{path}?ref={HEAD}", monotonic() + 2)


def test_worker_caps_inherited_output_file(tmp_path):
    with (tmp_path / "output").open("w+b") as output:
        subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c",
             f"import os, runpy; runpy.run_path({str(syntax._WORKER)!r})['restrict'](); "
             f"os.write(1, b'x' * {2 * syntax.MAX_OUTPUT})"],
            cwd=tmp_path, env={}, stdout=output, stderr=subprocess.DEVNULL,
            timeout=2, check=False,
        )
        assert output.seek(0, 2) == syntax.MAX_OUTPUT
