"""Shared plan fixtures: an empty current-schema factory.db in memory, one admitted attempt in a factory.db file, a semantic
Git fake clone and a slot root."""

import hashlib
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from git_porcelain.testing import FakeRemote, FakeRepo
from sqlite_store import Store, begin_immediate

from taskloop.plan_schema import SCHEMA


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
def admitted(tmp_path: Path) -> Path:
    """`<tmp>/factory.db` holding one admitted, unregistered attempt (deadline 100) and its held reservation; the
    artifacts root is `tmp_path`, with the admitted input written."""
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    text = "Plan the actual task"
    with begin_immediate(con):
        con.execute("INSERT INTO reservation VALUES ('slot','repo',?,1,'attempt')", (str(tmp_path),))
        con.execute(
            """INSERT INTO plan_attempt
            (attempt_id,dispatch_token,generation,adapter,backlog,task_id,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline)
            VALUES ('attempt','dispatch',1,'beads','tasks','tl-1','repo','slot','input.txt',?,1,'chosen','high','workspace-write',100)""",
            (hashlib.sha256(text.encode()).hexdigest(),),
        )
    con.close()
    (tmp_path / "input.txt").write_text(text)
    return path
