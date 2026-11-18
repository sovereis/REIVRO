# Regression Test Generator validation

Baseline was SCOP main at `22f0389`, the merge commit for PR #1. The skill was exercised by drafting two proposals using real public issue reports. Each proposed assertion is labeled as inferred.

| Proposal | Public evidence | Structure | Live quotes | Upstream execution |
| --- | --- | --- | --- | --- |
| Empty-source highlighting | [pytest #11758](https://github.com/pytest-dev/pytest/issues/11758) | Pass | 3 matched | Not run |
| Duplicate session fixture teardown | [pytest #12021](https://github.com/pytest-dev/pytest/issues/12021), [pytest-xdist #1024](https://github.com/pytest-dev/pytest-xdist/issues/1024) | Pass | 3 matched | Not run |

## Reproduce the SCOP checks

Run from the SCOP root with Python 3. Live checks require read access to GitHub's public API.

```sh
python -B tests/bug-regression-test/validate.py
python -B tests/bug-regression-test/validate.py --live
python -B -m unittest discover -s tests/bug-regression-test -p 'test_*.py' -v
```

Structure and live source checks each returned **2 passed, 0 blocked, 0 failed**. Live mode matched all six quotations across three issue bodies. The local validator suite returned **8 passed, 0 failed**. It explicitly rejected missing trigger or symptom evidence, missing or unrelated references, a fabricated quotation, unsupported factual and execution claims, and an unlabeled inference. A mock isolates the local quotation tests from network access.

The existing Pull Request Summary suite was also rerun using its [documented commands](../pr-source-summary/REPORT.md). Its structure and live checks each returned **3 passed, 0 blocked, 0 failed**, with 14 live references matched. All **13** of its local regression tests passed.

## Limits of the initial proposal-only pass

The initial pass ran no proposed tests against upstream pytest or pytest-xdist. The local interpreter did not have pytest installed, and this run did not provision pinned affected and corrected environments. Runtime predictions, worker coordination, and compatibility remain unverified. Quote matching verifies the text of the reports. Reviewers still need to assess whether the proposed assertions target the reported behavior.

The initial pass supported prototype review. The follow-up below records the runtime evidence used for advancement.

## Upstream execution follow-up

**Both proposals passed upstream validation.** Each probe failed with the reported symptom on the affected revision and passed on the fixing revision. Two complete runs produced the same outcomes.

| Issue | Affected revision and result | Fixing revision and result |
| --- | --- | --- |
| [pytest #11758](https://github.com/pytest-dev/pytest/issues/11758) | [8.0.0rc1 at `e17d5ec871998246a87ecd3a99bbfe4e67331847`](https://github.com/pytest-dev/pytest/commit/e17d5ec871998246a87ecd3a99bbfe4e67331847), exit 1 | [`cb5a42c836744181229b522611084a70220e4e33`](https://github.com/pytest-dev/pytest/commit/cb5a42c836744181229b522611084a70220e4e33), exit 0 |
| [pytest #12021](https://github.com/pytest-dev/pytest/issues/12021) | [8.0.0 at `478f8233bca8147445f0c5129f04ada892cc6c91`](https://github.com/pytest-dev/pytest/commit/478f8233bca8147445f0c5129f04ada892cc6c91), regression exit 1 | [`93cd7ba857471dc9f2322246f37ec5eb10cbc91c`](https://github.com/pytest-dev/pytest/commit/93cd7ba857471dc9f2322246f37ec5eb10cbc91c), regression exit 0 |

The #11758 issue timeline references the fix commit. Its diff adds an empty-string early return and a terminal-writer test. The SCOP probe calls the narrower `_highlight` entry point from the proposal and verifies that markup is active with a nonempty input. For #12021, the issue links the xdist report and merged PR #12022 removes the forced teardown path. The affected revision is the reported 8.0.0 release, and the fixed revision is the PR merge commit. [#11758 timeline](https://api.github.com/repos/pytest-dev/pytest/issues/11758/timeline) · [pytest-xdist #1024](https://github.com/pytest-dev/pytest-xdist/issues/1024) · [Fix PR #12022](https://github.com/pytest-dev/pytest/pull/12022)

### Observed output

```text
#11758 affected
IndexError: string index out of range
highlight exit=1

#11758 fixed
PASS: empty source returns an empty string with highlighting enabled
highlight exit=0

#12021 affected, --maxfail=1
E       Failed: SCOP deliberate failure
maxfail child exit=2
{'gw1': ['setup', 'teardown'], 'gw0': ['setup', 'teardown', 'setup', 'teardown']}
AssertionError: duplicate session fixture teardown
maxfail regression exit=1

#12021 fixed, --maxfail=1
E       Failed: SCOP deliberate failure
maxfail child exit=2
{'gw1': ['setup', 'teardown'], 'gw0': ['setup', 'teardown']}
PASS: each worker finalized exactly once
maxfail regression exit=0
```

Both no-limit controls returned child exit 1 for the deliberate failure and regression exit 0 with one teardown per worker. The max-fail child exit 2 was xdist's expected `Interrupted: stopping after 1 failures` result. The regression result comes from the separate marker checker. Initial xdist attempts encountered missing generated version metadata and a log-check assumption about the child exit and truncated summary. Those attempts were incomplete. Supplying local version metadata and checking the full failure line resolved the setup issues.

### Reproduce upstream runs

The runs used Linux and Python 3.12.14. Review the pinned revisions and wheel contents before execution. The run inspected pytest dependency declarations, the relevant terminal writer and runner paths, wheel metadata and entry points, the Pygments highlighting entry point, and the xdist/execnet local worker path. It unpacked inspected pure-Python wheels directly without running project build hooks or package installation scripts. The probes used a cleared environment, a temporary home, explicit source paths, and timeouts. Only the xdist plugin was enabled in the child test suite.

```bash
ROOT=$(mktemp -d /tmp/scop-upstream.XXXXXX)
cd "$ROOT"
git -c core.hooksPath=/dev/null clone --filter=blob:none --no-checkout https://github.com/pytest-dev/pytest.git repo
git -C repo -c core.hooksPath=/dev/null worktree add --detach ../highlight-affected e17d5ec871998246a87ecd3a99bbfe4e67331847
git -C repo -c core.hooksPath=/dev/null worktree add --detach ../highlight-fixed cb5a42c836744181229b522611084a70220e4e33
git -C repo -c core.hooksPath=/dev/null worktree add --detach ../xdist-affected 478f8233bca8147445f0c5129f04ada892cc6c91
git -C repo -c core.hooksPath=/dev/null worktree add --detach ../xdist-fixed 93cd7ba857471dc9f2322246f37ec5eb10cbc91c
python -m pip --isolated download --no-deps --only-binary=:all: --index-url https://pypi.org/simple --dest wheels \
    iniconfig==2.0.0 packaging==23.2 pluggy==1.4.0 Pygments==2.17.2 pytest-xdist==3.5.0 execnet==2.0.2
mkdir -p deps empty-home
python -B - <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
for wheel in Path("wheels").glob("*.whl"):
    with ZipFile(wheel) as archive:
        for name in archive.namelist():
            path = PurePosixPath(name)
            assert not path.is_absolute() and ".." not in path.parts
            assert not name.endswith((".pth", ".so", ".dll", ".pyd")) and ".data/" not in name
        archive.extractall("deps")
PY
printf 'version = "8.0.0"\nversion_tuple = (8, 0, 0)\n' > xdist-affected/src/_pytest/_version.py
printf 'version = "8.1.0.dev0"\nversion_tuple = (8, 1, 0, "dev0")\n' > xdist-fixed/src/_pytest/_version.py
```

The two version modules supply metadata normally generated during packaging. The probes exercise the checked-out pytest source. Save the following four files in the temporary root, then run `bash run-probes.sh > results.log 2>&1`. The script prints individual process exit codes and continues through the expected failures.

#### `highlight.py`

```python
from io import StringIO
from pathlib import Path

import _pytest
from _pytest._io.terminalwriter import TerminalWriter

assert Path(_pytest.__file__).resolve().is_relative_to(Path.cwd() / "src")
writer = TerminalWriter(StringIO())
writer.hasmarkup = True
writer.code_highlight = True
assert "\x1b[" in writer._highlight("assert True")
assert writer._highlight("") == ""
print("PASS: empty source returns an empty string with highlighting enabled")
```

#### `test_fixture.py`

```python
from pathlib import Path
from time import monotonic, sleep

import pytest


MARKERS = Path.cwd() / "markers"


@pytest.fixture(scope="session", autouse=True)
def session_fixture(worker_id):
    with (MARKERS / worker_id).open("a") as markers:
        markers.write("setup\n")
    yield
    with (MARKERS / worker_id).open("a") as markers:
        markers.write("teardown\n")


def test_deliberate_failure():
    deadline = monotonic() + 5
    while not all((MARKERS / name).exists() for name in ("gw0", "gw1")):
        if monotonic() >= deadline:
            pytest.fail("worker barrier timed out")
        sleep(0.01)
    pytest.fail("SCOP deliberate failure")


@pytest.mark.parametrize("index", range(8))
def test_queued(index):
    sleep(0.15)
```

#### `check_markers.py`

```python
from pathlib import Path
import re
import sys

mode, child_exit, log_path = sys.argv[1:]
log = Path(log_path).read_text()
expected_exit = "2" if mode == "maxfail" else "1"
if child_exit != expected_exit or not re.search(r"^E +Failed: SCOP deliberate failure$", log, re.M):
    print("INCOMPLETE: expected the deliberate child failure")
    sys.exit(2)
if "ERROR " in log or "INTERNALERROR" in log or re.search(r"^E +Failed: worker barrier timed out$", log, re.M):
    print("INCOMPLETE: child runner reported additional errors")
    sys.exit(2)
events = {path.name: path.read_text().splitlines() for path in Path("markers").iterdir()}
print(events, flush=True)
if events.keys() != {"gw0", "gw1"} or any(
    rows not in (["setup", "teardown"], ["setup", "teardown", "setup", "teardown"])
    for rows in events.values()
):
    print("INCOMPLETE: unexpected worker event sequence")
    sys.exit(2)
assert all(rows == ["setup", "teardown"] for rows in events.values()), "duplicate session fixture teardown"
print("PASS: each worker finalized exactly once")
```

#### `run-probes.sh`

```bash
#!/bin/bash
set -u
root=$(pwd)
python=$(command -v python)
for tree in highlight-affected highlight-fixed; do
    (
        cd "$root/$tree" || exit 1
        cp "$root/highlight.py" scop_highlight.py
        git rev-parse HEAD
        env -i HOME="$root/empty-home" PATH=/usr/bin:/bin PYTHONPATH="$PWD/src:$root/deps" \
            timeout 20 "$python" -B -S scop_highlight.py
        printf 'highlight exit=%s\n' "$?"
    )
done
for tree in xdist-affected xdist-fixed; do
    for mode in maxfail control; do
        (
            cd "$root/$tree" || exit 1
            git rev-parse HEAD
            run=$(mktemp -d "$PWD/scop-$mode.XXXXXX") || exit 1
            cp "$root/test_fixture.py" "$root/check_markers.py" "$run"
            cd "$run" || exit 1
            mkdir markers
            printf '[pytest]\n' > pytest.ini
            args=()
            if [ "$mode" = maxfail ]; then args+=(--maxfail=1); fi
            env -i HOME="$root/empty-home" PATH=/usr/bin:/bin PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
                PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/$tree/src:$root/deps" \
                timeout 30 "$python" -B -S -m pytest -c pytest.ini --noconftest -p no:cacheprovider \
                -p xdist.plugin -n 2 -q -r fE "${args[@]}" test_fixture.py > child.log 2>&1
            child_exit=$?
            cat child.log
            printf '%s child exit=%s\n' "$mode" "$child_exit"
            "$python" -B -S check_markers.py "$mode" "$child_exit" child.log
            printf '%s regression exit=%s\n' "$mode" "$?"
        )
    done
done
```

### SCOP follow-up checks

Reran the structure, live evidence, and local regression commands for both skills. Skill 2 returned 2/2 structure passes, 2/2 live evidence passes with six matched quotes, and 8/8 unit tests. Skill 1 returned 3/3 structure passes, 3/3 live evidence passes with 14 matched references, and 13/13 unit tests. None were blocked.

The proposal JSON and its validator describe the original proposal-only pass. This report records the later upstream executions. The two upstream cases validate the skill in the tested Linux/Python environment. Other Python, dependency, and agent combinations remain untested.
