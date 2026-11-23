"""Offline contracts for the public PR verifier."""
import pytest

from server import scop_verify as verifier
from server.scop_github_evidence import GITHUB_READ, _Unavailable
from server.scop_runtime import Status

PR = "https://github.com/pallets/click/pull/3412"
HEAD = "e6cfbbf0aa9f770db120fac5ab55499711e73395"
PATH = "tests/typing/typing_file.py"


@pytest.fixture
def source(monkeypatch):
    metadata = {"head": {"sha": HEAD}, "base": {"sha": "a" * 40}, "changed_files": 1}
    files = {PATH: {"patch": "@@ -7,3 +7,3 @@\n context \n-removed \n"
                            "+clean\n end\n@@ -12 +12,2 @@\n context\n+import _typeshed as ts ",
                    "additions": 2, "deletions": 1}}
    monkeypatch.setattr(verifier, "_fetch_metadata", lambda *args: ("endpoint", metadata))
    monkeypatch.setattr(verifier, "_fetch_files", lambda *args: files)
    return metadata, files


def test_evidence_points_to_added_head_line(source):
    report = verifier.verify(PR, (GITHUB_READ,))
    assert report.status == Status.COMPLETED
    assert (report.python_files_checked, report.added_lines_checked, report.finding_count) == (1, 2, 1)
    finding, = report.findings
    assert (finding.file, finding.line, finding.commit, finding.rule) == (PATH, 13, HEAD, verifier.RULE)
    assert finding.diff_url.endswith("R13")
    assert finding.commit_file_url.endswith(f"/blob/{HEAD}/{PATH}#L13")
    assert finding.excerpt == "+import _typeshed as ts "


def test_context_deletions_and_non_python_files_do_not_trigger(source):
    metadata, files = source
    metadata["changed_files"] = 2
    files["README.md"] = {"patch": "@@ -0,0 +1 @@\n+Markdown hard break  "}
    files[PATH]["patch"] = "@@ -1,2 +1,2 @@\n context \n-removed \n+clean"
    files[PATH]["additions"] = 1
    report = verifier.verify(PR, (GITHUB_READ,))
    assert report.status == Status.COMPLETED
    assert report.finding_count == 0
    assert report.added_lines_checked == 1


@pytest.mark.parametrize("patch", [None, "@@ -0,0 +1,2 @@\n+trailing "])
def test_missing_or_incomplete_evidence_withholds_findings(source, patch):
    _, files = source
    files[PATH]["patch"] = patch
    report = verifier.verify(PR, (GITHUB_READ,))
    assert report.status == Status.BLOCKED
    assert report.finding_count is None
    assert not report.findings


def test_revision_change_blocks_report(source, monkeypatch):
    metadata, _ = source
    revisions = iter([metadata, {**metadata, "head": {"sha": "b" * 40}}])
    monkeypatch.setattr(verifier, "_fetch_metadata", lambda *args: ("endpoint", next(revisions)))
    report = verifier.verify(PR, (GITHUB_READ,))
    assert report.status == Status.BLOCKED
    assert report.finding_count is None


@pytest.mark.parametrize("error, expected", [
    (_Unavailable("GitHub evidence could not be retrieved"), Status.BLOCKED),
    (RuntimeError("private diagnostic"), Status.FAILED),
    (KeyboardInterrupt(), Status.CANCELLED),
])
def test_fetch_errors_dont_report_success(monkeypatch, error, expected):
    def fail(*args):
        raise error

    monkeypatch.setattr(verifier, "_fetch_metadata", fail)
    report = verifier.verify(PR, (GITHUB_READ,))
    assert report.status == expected
    assert report.finding_count is None
    assert "private diagnostic" not in report.error


def test_invalid_url_and_missing_permission_never_fetch(monkeypatch):
    def unexpected(*args):
        pytest.fail("Network called before validation")

    monkeypatch.setattr(verifier, "_fetch_metadata", unexpected)
    assert verifier.verify(PR).status == Status.BLOCKED
    assert verifier.verify("https://example.org", (GITHUB_READ,)).status == Status.FAILED
