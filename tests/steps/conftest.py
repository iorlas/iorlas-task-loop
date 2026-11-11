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
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from sqlite_store import Store, begin_immediate

from taskloop.factory_schema import SCHEMA


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
def checkouts(repo: FakeRepo) -> PinnedViews:
    """The body's Git view of every checkout path: the fake clone, which finds a worktree by its path, as the real Git
    does from any checkout of the repository; a slot opens only pinned to its pointer's G (`PinnedViews`)."""
    return PinnedViews(repo)


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
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s1',?)", (repo_id, str(slot.path)))  # adopted
        con.execute("INSERT INTO reservation VALUES ('s1',?,1,'attempt')", (repo_id,))
        con.execute(
            """INSERT INTO attempt
            (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline,number,seq,slot_head)
            VALUES ('attempt','dispatch',1,'plan','beads','tasks','tl-1','/tracker',?,'s1','input.txt',?,1,'chosen','high',
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
        factory.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s1',?)", (repo_id, str(slot.path)))  # adopted
        factory.execute("INSERT INTO reservation VALUES ('s1',?,1,'attempt')", (repo_id,))
        factory.execute(
            """INSERT INTO attempt
            (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot,number,seq,slot_head)
            VALUES ('attempt','dispatch',1,'plan','beads','tasks','tl-1','/tracker',?,'s1','input.txt',?,1,'chosen','high',
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
