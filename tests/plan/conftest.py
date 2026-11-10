"""Shared plan fixtures: an empty current-schema factory.db in memory, one admitted attempt in a factory.db file, a semantic
Git fake clone, a slot root, a clean detached slot, the Git view the body opens, and an entry-registered attempt on it."""

import hashlib
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from git_porcelain import Repo
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from sqlite_store import Store, begin_immediate

from taskloop.plan_schema import SCHEMA
from taskloop.plan_types import Checkouts


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


@pytest.fixture
def admitted(tmp_path: Path, slot: FakeWorktree) -> Path:
    """`<tmp>/factory.db` holding one admitted, unregistered attempt (deadline 100) on `slot` and its held reservation;
    the artifacts root is `tmp_path`, with the admitted input written."""
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    text = "Plan the actual task"
    repo_id = slot.repo.identity().key
    with begin_immediate(con):
        con.execute("INSERT INTO reservation VALUES ('s1',?,?,1,'attempt')", (repo_id, str(slot.path)))
        con.execute(
            """INSERT INTO plan_attempt
            (attempt_id,dispatch_token,generation,adapter,backlog,task_id,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline)
            VALUES ('attempt','dispatch',1,'beads','tasks','tl-1',?,'s1','input.txt',?,1,'chosen','high','workspace-write',100)""",
            (repo_id, hashlib.sha256(text.encode()).hexdigest()),
        )
    con.close()
    (tmp_path / "input.txt").write_text(text)
    return path


@pytest.fixture
def registered(factory: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path) -> sqlite3.Connection:
    """In memory: one admitted, entry-registered attempt (entry (7, entry-start, boot), deadline 100) on `slot`, its held
    reservation, and its input in the artifacts root `tmp_path`."""
    repo_id = slot.repo.identity().key
    with begin_immediate(factory):
        factory.execute("INSERT INTO reservation VALUES ('s1',?,?,1,'attempt')", (repo_id, str(slot.path)))
        factory.execute(
            """INSERT INTO plan_attempt
            (attempt_id,dispatch_token,generation,adapter,backlog,task_id,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot)
            VALUES ('attempt','dispatch',1,'beads','tasks','tl-1',?,'s1','input.txt',?,1,'chosen','high',
            'workspace-write',100,7,'entry-start','boot')""",
            (repo_id, hashlib.sha256(b"Plan the actual task").hexdigest()),
        )
    (tmp_path / "input.txt").write_text("Plan the actual task")
    return factory
