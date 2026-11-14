"""A released implement/checks source with semantic slots and a real retained artifact."""

import json
import sqlite3
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from doubles import CHECKS, Environment, FakeSlotFiles, PinnedViews
from git_porcelain import Recorded
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from merge_bench import MergeRepo, head
from sqlite_store import Store

from taskloop.agents.launch import AgentLaunch
from taskloop.attempt_loads import AttemptLoads
from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.ids import NativeIds
from taskloop.land_conflict.admit import Ports, admit
from taskloop.land_conflict.execute import Ports as ExecutionPorts
from taskloop.land_conflict.execute import execute
from taskloop.land_conflict.models import Record, Request
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Disposition, Result
from taskloop.merge.store import MergeStore
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


def execution_repo(tmp_path: Path) -> FakeRepo:
    remote = FakeRemote("https://example.invalid/repo.git")
    remote.advance("main", {"README": "base\n", ".task-loop.json": "{}"})
    return MergeRepo.clone(remote, tmp_path / "main")


@dataclass
class ExecutionCase:
    path: Path
    con: sqlite3.Connection
    record: Record
    ports: ExecutionPorts
    slot: FakeWorktree
    environment: Environment
    calls: int = 0
    disposition: Disposition = Disposition.RESOLVED
    gone: bool = True
    interrupt: bool = False

    def run(self, harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        self.calls += 1
        assert hooks is not None and hooks.started is not None
        worker = Worker(pid=42 + self.calls, pgid=42 + self.calls, start=f"start-{self.calls}", boot="boot")
        hooks.started(worker)
        if self.interrupt:
            raise KeyboardInterrupt
        paths = []
        if self.disposition is Disposition.RESOLVED:
            self.slot.write_file("README", "X\ncurrent main\n")
            paths = ["README"]
        text = json.dumps({"disposition": self.disposition, "paths": paths, "explanation": "Retain both sides."})
        raw = RunOutcome(rc=0, worker=worker, summary=Summary(text=text, rc=0, stands=True, res={"ref": f"session-{self.calls}"}))
        return FakeRun(raw)(harness, spec, timeout, hooks)

    def resume(self, key: AttemptKey | None = None) -> Result:
        return execute(self.ports, self.record.key if key is None else key)

    def restart(self) -> None:
        self.con.close()
        con = Store(SCHEMA).open_rw(self.path)
        assert con is not None
        self.con = con
        self.environment.con = con
        self.ports = ExecutionPorts(ConflictStore(lambda: con), MergeStore(lambda: con), self.ports.repo,
            self.ports.checkouts, self.ports.remotes, self.ports.files, self.ports.evidence, self.ports.agent,
            self.run, lambda _worker: self.gone, self.ports.clock, self.environment.preparation(),
            self.ports.renew, self.ports.credentials, self.ports.probe)


def execution_case(on_slot: Path, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path) -> Generator[ExecutionCase]:
    b = bench(on_slot, repo, tmp_path)
    author = repo.add_worktree(tmp_path / "author", head(slot))
    author.write_file("README", "current main\n")
    target = author.record("current main", paths="all")
    assert isinstance(target, Recorded)
    repo.drop_worktree(author.path)
    repo.update_ref("refs/heads/task/tl-1", b.request.checked, expected=None)
    admitted = admit(b.ports, b.request.model_copy(update={"target": str(target.sha)}))
    assert admitted.record is not None
    views = PinnedViews(repo)
    environment = Environment(b.con, views, tmp_path / "artifacts", tmp_bytes=4096)
    ports = ExecutionPorts(b.ports.store, MergeStore(lambda: b.con), repo, views, views, FakeSlotFiles(repo), b.ports.files,
        AgentLaunch(lambda _h: ("/bin/codex", {}), ids=NativeIds()), lambda *_args: pytest.fail("unwired agent"),
        lambda _worker: True, lambda: 10, environment.preparation(), lambda: "held", ("/bin/codex", {}), ("probe",))
    case = ExecutionCase(on_slot, b.con, admitted.record, ports, slot, environment)
    case.restart()
    try:
        yield case
    finally:
        case.con.close()
