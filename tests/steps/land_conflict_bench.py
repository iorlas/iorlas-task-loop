"""A released implement/checks source with semantic slots and a real retained artifact."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from doubles import CHECKS, FakeSlotFiles, PinnedViews
from git_porcelain.testing import FakeRepo
from sqlite_store import Store

from taskloop.attempt_loads import AttemptLoads
from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.ids import NativeIds
from taskloop.land_conflict.admit import Ports
from taskloop.land_conflict.models import Request
from taskloop.land_conflict.store import ConflictStore
from taskloop.slots import SlotGit


@dataclass
class Bench:
    con: sqlite3.Connection
    ports: Ports
    request: Request
    artifact: Path


def bench(path: Path, repo: FakeRepo, tmp_path: Path) -> Bench:
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    files = EvidenceFiles(tmp_path / "artifacts")
    key = AttemptKey("implement", "implement-token", 1)
    ref = files.put_input(key, "The exact retained requirements.\n")
    con.execute("UPDATE attempt SET input_path=?,input_digest=?", (ref.path, ref.digest))
    con.execute("UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5,released_at=6,parked=slot_head")
    con.execute("DELETE FROM reservation WHERE attempt_id='checks'")
    checked = con.execute("SELECT end_commit FROM attempt WHERE attempt_id='implement'").fetchone()[0]
    request = Request(source=key, checks=CHECKS, repo_id=repo.identity().key, backlog="tasks", task_id="tl-1",
                      tracker_root="/tracker", checked=checked, target="e" * 40, deadline=300)
    ports = Ports(ConflictStore(lambda: con), AttemptLoads(lambda: con), files, repo,
                  SlotGit(PinnedViews(repo), FakeSlotFiles(repo)), lambda _: True, lambda: 10, NativeIds())
    return Bench(con, ports, request, files.root / ref.path)


def copy_row(con: sqlite3.Connection, table: str, identity: str, changes: dict[str, object]) -> None:
    """Another source/checks fixture row, preserving the schema's unrelated required facts."""
    cursor = con.execute(f"SELECT * FROM {table} WHERE attempt_id=?", (identity,))
    values = dict(zip((column[0] for column in cursor.description), cursor.fetchone(), strict=True)) | changes
    con.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
