#!/bin/sh
# Export a consistent SQLite image to a private file for encrypted storage.
set -eu
umask 077
python3 - "$@" <<'PY'
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import sys

source, target = map(Path, sys.argv[1:])
fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
try:
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        with closing(sqlite3.connect(target)) as backup:
            db.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
except Exception:
    target.unlink()
    raise
PY
