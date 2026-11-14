"""The body's slot check just before dispatch: B is the slot HEAD it reads, and only a born, clean slot of the admitted
repository, on its task branch (taken from a detached slot), dispatches; real SQLite, the owning agent fake and the
semantic Git fake."""

import json
import sqlite3
from pathlib import Path
from typing import ClassVar

import pytest
from any_agent import CodexHarness, Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from git_porcelain import Repo, Sha, WorktreeInfo
from git_porcelain.testing import FakeRepo, FakeWorktree

from taskloop.agents.launch import AgentLaunch
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, SlotFiles
from taskloop.evidence_files import EvidenceFiles
from taskloop.ids import NativeIds

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "Plan written"}


class CountingHarness(CodexHarness):
    """The real Codex harness, counting cleanups."""

    cleanups: ClassVar[list[int]] = []

    def cleanup(self) -> None:
        CountingHarness.cleanups.append(1)
        super().cleanup()


@pytest.fixture
def con(registered: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setattr("taskloop.agents.launch.CodexHarness", CountingHarness)
    monkeypatch.setattr(CountingHarness, "cleanups", [])
    return registered


def attempts(con: sqlite3.Connection, tmp_path: Path, run: FakeRun, checkouts: Checkouts, files: SlotFiles) -> Attempts:
    return Attempts(
        AttemptStore(lambda: con),
        EvidenceFiles(tmp_path),
        AgentLaunch(lambda _harness: ("/bin/codex", {}), ids=NativeIds()),
        run,
        lambda: 10,
        checkouts,
        files,
    )


def run() -> FakeRun:
    return FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), rc=0, stands=True)))


def head(repo: FakeRepo, path: Path) -> Sha | None:
    return next(worktree.head for worktree in repo.worktrees() if worktree.path == path)


def test_the_dispatch_records_the_slot_head_as_base_and_keeps_the_fenced_admission(
    con: sqlite3.Connection, slot: FakeWorktree, repo: FakeRepo, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    store = AttemptStore(lambda: con)
    before = store.load(KEY)
    assert before is not None and before.base_commit is None
    agent = run()
    result = attempts(con, tmp_path, agent, checkouts, slot_files).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("pending", "verification") and len(agent.calls) == 1
    after = store.load(KEY)
    assert after is not None and after.admission == before.admission  # B is not part of the fence: every later write passed
    assert after.base_commit == head(repo, slot.path) and after.phase == "captured"
    assert CountingHarness.cleanups == [1]


@pytest.mark.parametrize("mode", ["execute", "refused", "crashed"])
def test_worker_registration_commits_before_target_effects_and_refusal_forbids_them(
    con: sqlite3.Connection, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles, mode: str,
) -> None:
    effects: list[str] = []

    def gated(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert hooks is not None
        assert hooks.started is not None
        assert con.execute("SELECT phase,worker_pid FROM attempt").fetchone() == ("dispatching", None)
        if mode == "refused":
            con.execute("UPDATE attempt SET phase='admitted'")  # a callback fence changed before registration
        hooks.started(WORKER)
        assert not con.in_transaction
        assert con.execute("SELECT phase,worker_pid,worker_pgid,worker_start,worker_boot FROM attempt").fetchone() == (
            "registered", WORKER.pid, WORKER.pgid, WORKER.start, WORKER.boot,
        )
        if mode == "crashed":
            raise RuntimeError("entry lost after worker registration")
        effects.append("target executed")
        return run()(harness, spec, timeout, hooks)

    owner = attempts(con, tmp_path, run(), checkouts, slot_files)
    owner.execution = gated
    result = owner.execute(KEY, ENTRY)
    assert effects == (["target executed"] if mode == "execute" else [])
    expected = {"execute": ("pending", "verification"), "refused": ("conflict", "registration_conflict"),
                "crashed": ("unavailable", "run_failed:RuntimeError")}
    assert (result.status, result.reason) == expected[mode]
    if mode == "crashed":
        assert con.execute("SELECT phase,worker_pid FROM attempt").fetchone() == ("registered", WORKER.pid)
        assert con.execute("SELECT * FROM execution").fetchone() is None


def test_a_deadline_crossed_during_the_slot_read_never_dispatches(
    con: sqlite3.Connection, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    now = [10.0]

    def slow(path: Path, /, *, git_dir: Path | None = None) -> Repo:
        now[0] = 100.0  # the untimed Git reads outlast the deadline
        return checkouts(path, git_dir=git_dir)

    agent = run()
    store, files = AttemptStore(lambda: con), EvidenceFiles(tmp_path)
    owner = Attempts(store, files, AgentLaunch(lambda _harness: ("/bin/codex", {}), ids=NativeIds()), agent,
        lambda: now[0], slow, slot_files)
    result = owner.execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("refused", "expired") and agent.calls == [] and CountingHarness.cleanups == [1]
    assert con.execute("SELECT phase,rev,base_commit FROM attempt").fetchone() == ("admitted", 0, None)


@pytest.mark.parametrize(
    ("case", "status", "reason"),
    [
        ("unborn", "refused", "slot_unborn"),
        ("branch", "refused", "slot_branch"),
        ("taken_elsewhere", "refused", "branch_held"),
        ("dirty", "refused", "slot_dirty"),
        ("untracked", "refused", "slot_dirty"),
        ("missing", "unavailable", "git"),
        ("not_listed", "unavailable", "not_listed"),
        ("other_repo", "unavailable", "repo"),
    ],
)
def test_an_unusable_slot_never_dispatches_and_the_attempt_stays_admitted(
    con: sqlite3.Connection,
    slot: FakeWorktree,
    repo: FakeRepo,
    tmp_path: Path,
    checkouts: Checkouts,
    slot_files: SlotFiles,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    status: str,
    reason: str,
) -> None:
    if case == "unborn":
        listed = (WorktreeInfo(repo.path, head(repo, repo.path), "main", True, None), WorktreeInfo(slot.path, None, "orphan", False, None))
        monkeypatch.setattr(repo, "worktrees", lambda *, with_dirty=False: listed)
    elif case == "branch":
        slot.checkout_new("other")
    elif case == "taken_elsewhere":
        repo.add_worktree(slot.path.parent / "elsewhere", "HEAD").checkout_new("task/tl-1")
    elif case == "dirty":
        slot.write_file("README", "changed")
    elif case == "untracked":
        slot.write_file("scratch", "x")
    elif case == "missing":
        repo.drop_checkout(slot.path)
    elif case == "not_listed":
        assert slot_files.lstat(slot.path / ".git") is not None  # its pointer stays readable: only Git's registration goes
        repo.drop_worktree(slot.path)
    else:
        con.execute("UPDATE slot SET repo_id='other'")
        con.execute("UPDATE reservation SET repo_id='other'")
        con.execute("UPDATE attempt SET repo_id='other'")
    agent = run()
    running = attempts(con, tmp_path, agent, checkouts, slot_files)
    for _ in range(2):  # nothing moved: the same refusal again
        result = running.execute(KEY, ENTRY)
        assert (result.status, result.reason) == (status, reason)
    assert agent.calls == [] and CountingHarness.cleanups == [1, 1]
    assert con.execute("SELECT phase,rev,base_commit FROM attempt").fetchone() == ("admitted", 0, None)
