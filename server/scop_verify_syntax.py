"""Compare pinned Python sources and attribute physical syntax diagnostics."""
import base64
from binascii import Error as Base64Error
from hashlib import sha1
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
from tempfile import TemporaryDirectory, TemporaryFile
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import quote

from . import scop_github_evidence as github
from ._syntax_worker import MAX_OUTPUT, MAX_SOURCE
from .scop_verify import _HUNK, _SHA, _VALIDATOR_PATH, _added_lines, _parse_identity, _revision

RULE = "python-syntax-regression"
MAX_FILES = 12
_WORKER = Path(__file__).with_name("_syntax_worker.py").resolve()


class _Insufficient(Exception):
    """Evidence does not support a conclusion."""


class _Operational(Exception):
    """The check could not run."""


class _IsolationUnavailable(_Operational):
    """The executor could not establish its isolation contract."""


def _source(identity, revision, path, deadline, expected_sha=None):
    if (len(path) > 1024 or "\\" in path or any(ord(ch) < 32 for ch in path)
            or any(part in {"", ".", ".."} for part in path.split("/"))):
        raise _Insufficient("Unsupported source path")
    owner, repo, _ = identity
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{quote(path)}?ref={revision}"
    try:
        item = github.fetch_json(url, deadline)
    except github._Unavailable as exc:
        if isinstance(exc.__cause__, HTTPError) and exc.__cause__.code == 404:
            raise _Insufficient("Source unavailable at pinned revision") from exc
        raise
    if not isinstance(item, dict) or not (
        item.get("path") == path and item.get("type") == "file"
        and item.get("encoding") == "base64"
        and type(item.get("size")) is int and 0 <= item["size"] <= MAX_SOURCE
        and isinstance(item.get("content"), str)
        and isinstance(item.get("sha"), str) and _SHA.fullmatch(item["sha"])
    ):
        raise _Insufficient("Missing, unsupported or oversized pinned source")
    encoded = item["content"]
    if len(encoded) > 2 * MAX_SOURCE:
        raise _Insufficient("Encoded source exceeds limit")
    try:
        raw = base64.b64decode(encoded.replace("\n", ""), validate=True)
    except (Base64Error, ValueError) as exc:
        raise _Insufficient("Invalid source encoding from GitHub") from exc
    blob = sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw,
                usedforsecurity=False).hexdigest()
    if len(raw) != item["size"] or blob != item["sha"] or (
        expected_sha is not None and blob != expected_sha
    ):
        raise _Insufficient("Pinned source failed blob integrity checks")
    return raw


def _compile(source, deadline):
    if sys.platform != "linux" or sys.implementation.name != "cpython":
        raise _Operational("The compiler sandbox requires Linux and CPython")
    if len(source) > MAX_SOURCE:
        raise _Insufficient("Source exceeds compiler input limit")
    timeout = min(2, deadline - monotonic())
    if timeout <= 0:
        raise _Operational("Verification time budget exhausted")
    try:
        with TemporaryDirectory(prefix="reivro-syntax-") as directory, TemporaryFile(dir=directory) as output:
            proc = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-W", "ignore", str(_WORKER)],
                input=source, stdout=output, stderr=subprocess.DEVNULL,
                env={}, cwd=directory, close_fds=True, timeout=timeout, check=False,
            )
            if proc.returncode:
                raise _Operational("Compiler sandbox, resource limit or worker failure")
            output.seek(0)
            raw = output.read(MAX_OUTPUT + 1)
    except subprocess.TimeoutExpired as exc:
        raise _Operational("Compiler timed out") from exc
    if len(raw) > MAX_OUTPUT:
        raise _Operational("Compiler response exceeds output limit")
    return json.loads(raw)


def _lf_lines(text):
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _patch_lines(item, base, head):
    """Check that the PR patch accounts for both pinned file snapshots."""
    try:
        added = dict(_added_lines(item))
        if any(re.search(br"\r(?!\n)", raw) for raw in (base, head)):
            raise _Insufficient("Source has unsupported bare CR line endings")
        before, after = (_lf_lines(raw.decode("utf-8")) for raw in (base, head))
    except (github._Unavailable, UnicodeError) as exc:
        raise _Insufficient("Incomplete or unsupported patch evidence") from exc
    old = new = 0
    rows = item["patch"].removesuffix("\n").split("\n")
    marker = r"\ No newline at end of file"
    for index, row in enumerate(rows):
        header = _HUNK.fullmatch(row)
        if header:
            old_start, old_count, new_start, new_count = header.groups()
            old_next = int(old_start) - (old_count != "0")
            new_next = int(new_start) - (new_count != "0")
            if (not old <= old_next <= len(before) or not new <= new_next <= len(after)
                    or before[old:old_next] != after[new:new_next]):
                raise _Insufficient("Patch does not match the pinned comparison")
            old, new = old_next, new_next
        elif row.startswith((" ", "-", "+")):
            no_newline = index + 1 < len(rows) and rows[index + 1] == marker
            source_line = row[1:] if no_newline else row[1:] + "\n"
            if row[0] != "+":
                if old >= len(before) or before[old] != source_line:
                    raise _Insufficient("Patch does not match the pinned BASE")
                old += 1
            if row[0] != "-":
                if new >= len(after) or after[new] != source_line:
                    raise _Insufficient("Patch does not match the pinned HEAD")
                new += 1
        elif row == marker and (index == 0 or not rows[index - 1].startswith((" ", "-", "+"))):
            raise _Insufficient("Unexpected missing-newline marker")
    if before[old:] != after[new:]:
        raise _Insufficient("Patch does not cover the pinned comparison")
    return added


def _check_file(identity, head, base, path, item, deadline, executor):
    status = item.get("status")
    if status in {"added", "removed"}:
        return {"status": "INCONCLUSIVE", "reason": f"{status.capitalize()} file lacks a comparable pair"}
    previous = item.get("previous_filename") if status == "renamed" else path
    if (status not in {"modified", "renamed"} or not path.endswith(".py")
            or not isinstance(previous, str) or not previous.endswith(".py")):
        raise _Insufficient("Unsupported Python file transition")
    blob = item.get("sha")
    if not isinstance(blob, str) or not _SHA.fullmatch(blob):
        raise _Insufficient("Missing HEAD blob identity")
    before = _source(identity, base, previous, deadline)
    after = _source(identity, head, path, deadline, blob)
    if before == after and status == "renamed":
        changed = {}
    elif not item.get("patch"):
        raise _Insufficient("Python patch unavailable")
    else:
        changed = _patch_lines(item, before, after)
    baseline = executor(before, deadline)
    if baseline["kind"] != "valid":
        raise _Insufficient("BASE did not compile with the supported compiler")
    current = executor(after, deadline)
    if current["kind"] == "valid":
        return {"status": "PASS"}
    if current["kind"] != "syntax":
        raise _Insufficient("HEAD uses an unsupported source encoding")
    line = current["line"]
    if type(line) is not int or line != current["end_line"] or line not in changed:
        raise _Insufficient("Syntax diagnostic cannot be attributed to one added line")
    excerpt = changed[line]
    # A copied line may survive a reordering or be misaligned by a diff.
    if excerpt[1:].encode() in before.split(b"\n"):
        raise _Insufficient("Diagnostic line also occurs in BASE")
    owner, repo, _ = identity
    root = f"https://github.com/{owner}/{repo}"
    return {
        "status": "REGRESSION_DETECTED", "rule": RULE, "line": line,
        "exception": current["exception"], "diagnostic": current["message"],
        "excerpt": excerpt[:400], "excerpt_truncated": len(excerpt) > 400,
        "base_commit_url": f"{root}/commit/{base}", "head_commit_url": f"{root}/commit/{head}",
        "base_file_url": f"{root}/blob/{base}/{quote(previous)}",
        "head_file_url": f"{root}/blob/{head}/{quote(path)}#L{line}",
    }


def verify_syntax(pr_url, permissions=(), *, executor=None):
    executor = _compile if executor is None else executor
    report = {"rule": RULE, "status": "ERROR", "pr_url": None,
              "compiler": sys.version.split()[0], "files": []}
    if permissions != (github.GITHUB_READ,):
        return {**report, "status": "INCONCLUSIVE", "reason": "Explicit GitHub read permission required"}
    try:
        identity = _parse_identity(pr_url, runpy.run_path(str(_VALIDATOR_PATH)))
        if identity is None:
            return {**report, "reason": "Expected a canonical public GitHub PR URL"}
        report.update(pr_url=pr_url, repository="/".join(identity[:2]), pr=int(identity[2]))
        deadline = monotonic() + github._NETWORK_BUDGET_SECONDS
        endpoint, metadata = github._fetch_metadata(pr_url, identity, deadline)
        head, base, count = _revision(metadata)
        report.update(base_sha=base, head_sha=head)
        if type(count) is not int or not 0 <= count <= github._MAX_FILE_PAGES * 100:
            raise _Insufficient("PR file count is missing or exceeds the fetch limit")
        files = github._fetch_files(endpoint, deadline)
        if len(files) != count:
            raise _Insufficient("GitHub returned an incomplete file list")
        python_files = {path: item for path, item in files.items() if path.endswith(".py") or (
            isinstance(item.get("previous_filename"), str) and item["previous_filename"].endswith(".py"))}
        if not 0 < len(python_files) <= MAX_FILES:
            raise _Insufficient("No Python files or Python file limit exceeded")
        results = []
        for path, item in sorted(python_files.items()):
            try:
                result = _check_file(identity, head, base, path, item, deadline, executor)
            except _Insufficient as exc:
                result = {"status": "INCONCLUSIVE", "reason": str(exc)}
            except _IsolationUnavailable:
                raise
            except (_Operational, github._Unavailable) as exc:
                result = {"status": "ERROR", "reason": str(exc)}
            results.append({"file": path, **result})
        _, latest = github._fetch_metadata(pr_url, identity, deadline)
        if _revision(latest) != (head, base, count):
            raise _Insufficient("PR revision changed during verification; retry")
        statuses = {result["status"] for result in results}
        overall = next(status for status in ("REGRESSION_DETECTED", "ERROR", "INCONCLUSIVE", "PASS")
                       if status in statuses)
        report["compiler"] = getattr(executor, "compiler_version", None) or report["compiler"]
        return {**report, "status": overall, "files": results}
    except _Insufficient as exc:
        return {**report, "status": "INCONCLUSIVE", "reason": str(exc)}
    except (github._Unavailable, _Operational) as exc:
        return {**report, "reason": str(exc)}
    except Exception:
        return {**report, "reason": "Syntax verification could not complete"}
