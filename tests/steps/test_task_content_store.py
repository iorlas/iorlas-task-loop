"""Durable, immutable plan evidence participates in its admission transaction."""

import sqlite3
from pathlib import Path

import pytest
from git_porcelain.testing import FakeRepo
from sqlite_store import Store, begin_immediate
from test_admit import Tracker, admission, request, slots, tasks
from test_repeat import CONTENT_DIGEST

from taskloop.admit import Admitted
from taskloop.factory_schema import SCHEMA
from taskloop.task_content_store import TaskContentStore


def test_admitted_evidence_survives_reopen_and_task_edits(tmp_path: Path, repo: FakeRepo) -> None:
    database = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(database)
    assert con is not None
    slots(con, repo, tmp_path / "slots", 1)
    tracker = Tracker(con, tmp_path / "artifacts")
    app = admission(con, tmp_path, tracker, repo)
    result = app.admit(request(tmp_path, repo))
    assert isinstance(result, Admitted)
    saved = TaskContentStore(lambda: con).read(result.key.attempt_id)
    assert saved is not None
    app.tasks = lambda task_id, backlog, root: tasks("tl-2", backlog, root)
    con.close()
    reopened = Store(SCHEMA).open_rw(database)
    assert reopened is not None
    assert TaskContentStore(lambda: reopened).read(result.key.attempt_id) == saved
    assert TaskContentStore(lambda: reopened).read("missing") is None
    reopened.close()


def test_duplicate_and_rolled_back_evidence_cannot_replace_saved_content(registered: sqlite3.Connection) -> None:
    store = TaskContentStore(lambda: registered)
    with pytest.raises(RuntimeError, match="admission failed"), begin_immediate(registered):
        TaskContentStore.insert(registered, "attempt", CONTENT_DIGEST)
        raise RuntimeError("admission failed")
    assert store.read("attempt") is None
    with begin_immediate(registered):
        TaskContentStore.insert(registered, "attempt", CONTENT_DIGEST)
    with pytest.raises(sqlite3.IntegrityError), begin_immediate(registered):
        TaskContentStore.insert(registered, "attempt", CONTENT_DIGEST)
    assert store.read("attempt") == CONTENT_DIGEST


@pytest.mark.parametrize("value", [None, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n"])
def test_database_rejects_invalid_digest(registered: sqlite3.Connection, value: object) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        registered.execute("INSERT INTO task_content (attempt_id,digest) VALUES ('attempt',?)", (value,))


def test_database_rejects_evidence_without_an_attempt(factory: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        TaskContentStore.insert(factory, "missing", CONTENT_DIGEST)
