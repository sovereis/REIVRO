"""Project-scoped local memory and repository artifact I/O for the firewall."""
from contextlib import closing, contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from uuid import uuid4


class FirewallError(Exception):
    """A request or authorization check failed."""


_REPO = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,38}/[a-zA-Z0-9_.-]{1,100}")
_ID = re.compile(r"[fp]-[0-9a-f]{64}")
MAX_ARTIFACT = 8192
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def project_key(repository):
    if not _REPO.fullmatch(repository) or repository.split("/")[1] in {".", ".."}:
        raise FirewallError("Expected a GitHub owner/repository")
    return repository.lower()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def identifier(prefix, value):
    return prefix + "-" + hashlib.sha256(canonical(value)).hexdigest()


def _outside_checkout(path):
    resolved = path.resolve()
    for parent in (resolved, *resolved.parents):
        marker = parent / ".git"
        if marker.is_file() or (marker / "HEAD").is_file():
            raise FirewallError("Memory must be outside a Git checkout")


def _private_directory(path):
    info = path.lstat()
    _outside_checkout(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise FirewallError("Memory directory must be private and owned by the current OS user")


class Memory:
    """An owner-only SQLite journal. Every state change appends an event."""

    def __init__(self, directory, repository):
        self.directory = Path(directory)
        self.repository = project_key(repository)
        self.actor = f"uid:{os.geteuid()}"
        self.path = self.directory / "firewall.sqlite3"

    def initialize(self):
        _outside_checkout(self.directory)
        self.directory.mkdir(mode=0o700, exist_ok=True)
        _private_directory(self.directory)
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE project (repository TEXT PRIMARY KEY, owner TEXT NOT NULL);
                CREATE TABLE events (
                    seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL,
                    actor TEXT NOT NULL, time TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE INDEX events_subject ON events(subject, seq);
            """)
            db.execute("INSERT INTO project VALUES (?, ?)", (self.repository, self.actor))
            self.append(db, "project_created", self.repository, {})

    @contextmanager
    def transaction(self, write=False):
        _private_directory(self.directory)
        info = self.path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise FirewallError("Memory database must be an owner-only regular file")
        db = sqlite3.connect(self.path, timeout=3)
        try:
            db.execute("PRAGMA trusted_schema = OFF")
            if not write:
                db.execute("PRAGMA query_only = ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            if db.execute("SELECT repository, owner FROM project").fetchall() != [
                (self.repository, self.actor)
            ]:
                raise FirewallError("Memory belongs to another project or operator")
            yield db
            db.commit()
        finally:
            db.close()

    def append(self, db, kind, subject, data):
        timestamp = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO events(kind, subject, actor, time, data) VALUES (?, ?, ?, ?, ?)",
                   (kind, subject, self.actor, timestamp, canonical(data).decode()))
        return {"kind": kind, "subject": subject, "actor": self.actor, "time": timestamp, "data": data}

    @staticmethod
    def history(db, subject=None):
        query = "SELECT kind, subject, actor, time, data FROM events"
        rows = db.execute(query + " ORDER BY seq") if subject is None else db.execute(
            query + " WHERE subject = ? ORDER BY seq", (subject,))
        return [{"kind": kind, "subject": subject, "actor": actor, "time": timestamp,
                 "data": json.loads(data)} for kind, subject, actor, timestamp, data in rows]


@contextmanager
def _artifact_directory(checkout, create):
    """Walk fixed names relative to an open directory, refusing symlink components."""
    with ExitStack() as stack:
        fd = os.open(checkout, _DIR_FLAGS)
        stack.callback(os.close, fd)
        for part in (".reivro", "protections"):
            if create:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            stack.callback(os.close, fd)
        yield fd


def artifact(checkout, protection_id, document=None):
    """Read the exact approved bytes, or publish a new file without overwriting."""
    if not _ID.fullmatch(protection_id) or not protection_id.startswith("p-"):
        raise FirewallError("Invalid protection ID")
    name = protection_id + ".json"
    with _artifact_directory(checkout, document is not None) as directory:
        if document is None:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise FirewallError("Protection artifact must be a regular file")
                return handle.read(MAX_ARTIFACT + 1)

        document = canonical(document) + b"\n"
        if len(document) > MAX_ARTIFACT:
            raise FirewallError("Protection artifact exceeds limit")
        temporary = ".export-" + uuid4().hex
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644,
                     dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(document)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            os.fsync(directory)
        finally:
            os.unlink(temporary, dir_fd=directory)
    return str(Path(checkout) / ".reivro" / "protections" / name)
