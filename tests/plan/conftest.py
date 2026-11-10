"""Shared plan fixtures: an empty current-schema factory.db in memory, one admitted attempt in a factory.db file, a semantic
Git fake clone, a slot root, a clean detached slot, the Git view the body opens, the slot file port over the fake, an
entry-registered attempt on it, and another holder of a slot's lock."""

import fcntl
import hashlib
import os
import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from git_porcelain import GitUnavailable, Repo
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from sqlite_store import Store, begin_immediate

from taskloop.plan_schema import SCHEMA
from taskloop.plan_types import Checkouts, FileEntry


@pytest.fixture
def factory() -> Generator[sqlite3.Connection]:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.execute("PRAGMA foreign_keys=ON")
    with begin_immediate(con):
        for statement in SCHEMA.ddl.split(";"):
            if statement.strip():
                con.execute(statement)
        con.execute(f"PRAGMA user_version={SCHEMA.version}")
    yield con
    con.close()


@pytest.fixture
def repo(tmp_path: Path) -> FakeRepo:
    remote = FakeRemote("https://example.invalid/repo.git")
    remote.advance("main", {"README": "one"})
    return FakeRepo.clone(remote, tmp_path / "main")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "slots"


@pytest.fixture
def slot(repo: FakeRepo, root: Path) -> FakeWorktree:
    """What a person does before adoption: `git worktree add --detach <root>/<repo_id>/s1`, born, detached and clean."""
    return repo.add_worktree(root.resolve() / repo.identity().key / "s1", "HEAD")


@pytest.fixture
def checkouts(repo: FakeRepo) -> Checkouts:
    """The body's Git view of every checkout path: the fake clone, which finds a worktree by its path, as the real Git
    does from any checkout of the repository."""

    def opened(_path: Path) -> Repo:
        return repo

    return opened


class FakeSlotFiles:
    """The slot file port over the Git fake: each linked worktree it has seen listed keeps a valid pointer into the fake's
    common directory (with its `commondir` and `gitdir` back-pointer), and its files are the fake checkout's, regular and
    0644. `entries` and `contents` override any path: a rewritten pointer, a symlink, a FIFO, an executable file."""

    def __init__(self, repo: FakeRepo) -> None:
        self.repo, self.common = repo, repo.identity().common_dir
        self.known: dict[Path, FakeWorktree] = {}
        self.entries: dict[Path, FileEntry | None] = {}
        self.contents: dict[Path, bytes] = {}
        self.resolved: dict[Path, Path | None] = {}

    @property
    def slots(self) -> tuple[FakeWorktree, ...]:
        try:
            listed = self.repo.worktrees()
        except GitUnavailable:
            listed = ()
        for info in listed:
            if not info.is_main:
                self.known.setdefault(info.path, self.repo.worktree(info.path))
        return tuple(self.known.values())

    def _gitdir(self, slot: FakeWorktree) -> Path:
        return self.common / "worktrees" / slot.path.name

    @staticmethod
    def _files(slot: FakeWorktree) -> dict[str, bytes]:
        try:
            return slot.state().files
        except GitUnavailable:  # a dropped checkout has no files
            return {}

    def _data(self, path: Path) -> bytes | None:
        if path in self.contents:
            return self.contents[path]
        for slot in self.slots:
            pointers = {
                slot.path / ".git": f"gitdir: {self._gitdir(slot)}\n".encode(),
                self._gitdir(slot) / "commondir": b"../..\n",
                self._gitdir(slot) / "gitdir": f"{slot.path / '.git'}\n".encode(),
            }
            if path in pointers:
                return pointers[path]
            if path.is_relative_to(slot.path) and path != slot.path:
                return self._files(slot).get(path.relative_to(slot.path).as_posix())
        return None

    def _folder(self, path: Path) -> bool:
        for slot in self.slots:
            if path in (slot.path, self._gitdir(slot)):
                return True
            if path.is_relative_to(slot.path):
                prefix = path.relative_to(slot.path).as_posix() + "/"
                return any(name.startswith(prefix) for name in self._files(slot))
        return False

    def lstat(self, path: Path) -> FileEntry | None:
        if path in self.entries:
            return self.entries[path]
        data = self._data(path)
        if data is not None:
            return FileEntry("file", len(data), False)
        return FileEntry("dir", 0, False) if self._folder(path) else None

    def resolve(self, path: Path) -> Path | None:
        """No symlinks in the fake unless `resolved` names one; `..` folds as the operating system would."""
        return self.resolved.get(path, Path(os.path.normpath(path)))

    def read(self, path: Path, cap: int) -> bytes | None:
        entry = self.lstat(path)
        return None if entry is None or entry.kind != "file" or entry.size > cap else self._data(path)


@pytest.fixture
def slot_files(repo: FakeRepo) -> FakeSlotFiles:
    return FakeSlotFiles(repo)


def head(slot: FakeWorktree) -> str:
    """The slot's HEAD as Git lists it: for a freshly added slot, its admission base D."""
    found = next(worktree.head for worktree in slot.repo.worktrees() if worktree.path == slot.path)
    assert found is not None
    return found


@pytest.fixture
def admitted(tmp_path: Path, slot: FakeWorktree) -> Path:
    """`<tmp>/factory.db` holding one admitted, unregistered attempt (deadline 100) on the adopted `slot` and its held reservation;
    the artifacts root is `tmp_path`, with the admitted input written."""
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    text = "Plan the actual task"
    repo_id = slot.repo.identity().key
    with begin_immediate(con):
        con.execute("INSERT INTO slot (repo_id,name,cwd) VALUES (?,'s1',?)", (repo_id, str(slot.path)))  # adopted
        con.execute("INSERT INTO reservation VALUES ('s1',?,?,1,'attempt')", (repo_id, str(slot.path)))
        con.execute(
            """INSERT INTO plan_attempt
            (attempt_id,dispatch_token,generation,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline,number,seq,slot_head)
            VALUES ('attempt','dispatch',1,'beads','tasks','tl-1','/tracker',?,'s1','input.txt',?,1,'chosen','high',
            'workspace-write',100,1,1,?)""",
            (repo_id, hashlib.sha256(text.encode()).hexdigest(), head(slot)),
        )
    con.close()
    (tmp_path / "input.txt").write_text(text)
    return path


@pytest.fixture
def registered(factory: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path) -> sqlite3.Connection:
    """In memory: one admitted, entry-registered attempt (entry (7, entry-start, boot), deadline 100) on the adopted `slot`, its held
    reservation, and its input in the artifacts root `tmp_path`."""
    repo_id = slot.repo.identity().key
    with begin_immediate(factory):
        factory.execute("INSERT INTO slot (repo_id,name,cwd) VALUES (?,'s1',?)", (repo_id, str(slot.path)))  # adopted
        factory.execute("INSERT INTO reservation VALUES ('s1',?,?,1,'attempt')", (repo_id, str(slot.path)))
        factory.execute(
            """INSERT INTO plan_attempt
            (attempt_id,dispatch_token,generation,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot,number,seq,slot_head)
            VALUES ('attempt','dispatch',1,'beads','tasks','tl-1','/tracker',?,'s1','input.txt',?,1,'chosen','high',
            'workspace-write',100,7,'entry-start','boot',1,1,?)""",
            (repo_id, hashlib.sha256(b"Plan the actual task").hexdigest(), head(slot)),
        )
    (tmp_path / "input.txt").write_text("Plan the actual task")
    return factory


@contextmanager
def _occupied(path: Path) -> Generator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


@pytest.fixture
def occupy() -> Callable[[Path], AbstractContextManager[None]]:
    """Another holder of a slot's lock file: its own open file description holding the exclusive `flock`, as another
    process would hold it."""
    return _occupied
