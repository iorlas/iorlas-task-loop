"""The body's slot check just before dispatch: B is the slot HEAD it reads, and only a born, detached, clean slot of the
admitted repository dispatches; real SQLite, the owning agent fake and the semantic Git fake."""

import json
import sqlite3
from pathlib import Path
from typing import ClassVar

import pytest
from any_agent import CodexHarness, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from git_porcelain import Repo, Sha, WorktreeInfo
from git_porcelain.testing import FakeRepo, FakeWorktree

from taskloop.plan import PlanAttempts
from taskloop.plan_files import PlanFiles
from taskloop.plan_store import PlanStore
from taskloop.plan_types import AttemptKey, Checkouts

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
PLAN = {"disposition": "planned", "plan_path": "docs/design/tl-1/plan.md", "commit": "a" * 40, "explanation": "Plan committed"}


class Spy(CodexHarness):
    """The real Codex harness, counting cleanups."""

    cleanups: ClassVar[list[int]] = []

    def cleanup(self) -> None:
        Spy.cleanups.append(1)
        super().cleanup()


@pytest.fixture
def con(registered: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setattr("taskloop.plan.CodexHarness", Spy)
    monkeypatch.setattr(Spy, "cleanups", [])
    return registered


def body(con: sqlite3.Connection, tmp_path: Path, run: FakeRun, checkouts: Checkouts) -> PlanAttempts:
    return PlanAttempts(PlanStore(lambda: con), PlanFiles(tmp_path), lambda: ("/bin/codex", {}), run, lambda: 10, checkouts)


def run() -> FakeRun:
    return FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), rc=0, stands=True)))


def head(repo: FakeRepo, path: Path) -> Sha | None:
    return next(worktree.head for worktree in repo.worktrees() if worktree.path == path)


def test_the_dispatch_records_the_slot_head_as_base_and_keeps_the_fenced_admission(
    con: sqlite3.Connection, slot: FakeWorktree, repo: FakeRepo, tmp_path: Path, checkouts: Checkouts
) -> None:
    store = PlanStore(lambda: con)
    before = store.load(KEY)
    assert before is not None and before.base_commit is None
    agent = run()
    result = body(con, tmp_path, agent, checkouts).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("pending", "verification") and len(agent.calls) == 1
    after = store.load(KEY)
    assert after is not None and after.admission == before.admission  # B is not part of the fence: every later write passed
    assert after.base_commit == head(repo, slot.path) and after.phase == "captured"
    assert Spy.cleanups == [1]


def test_a_deadline_crossed_during_the_slot_read_never_dispatches(
    con: sqlite3.Connection, tmp_path: Path, checkouts: Checkouts
) -> None:
    now = [10.0]

    def slow(path: Path) -> Repo:
        now[0] = 100.0  # the untimed Git reads outlast the deadline
        return checkouts(path)

    agent = run()
    attempts = PlanAttempts(PlanStore(lambda: con), PlanFiles(tmp_path), lambda: ("/bin/codex", {}), agent, lambda: now[0], slow)
    result = attempts.execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("refused", "expired") and agent.calls == [] and Spy.cleanups == [1]
    assert con.execute("SELECT phase,rev,base_commit FROM plan_attempt").fetchone() == ("admitted", 0, None)


@pytest.mark.parametrize(
    ("case", "status", "reason"),
    [
        ("unborn", "refused", "slot_unborn"),
        ("branch", "refused", "slot_branch"),
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
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    status: str,
    reason: str,
) -> None:
    if case == "unborn":
        listed = (WorktreeInfo(repo.path, head(repo, repo.path), "main", True, None), WorktreeInfo(slot.path, None, "orphan", False, None))
        monkeypatch.setattr(repo, "worktrees", lambda *, with_dirty=False: listed)
    elif case == "branch":
        slot.checkout_new("task/tl-1")
    elif case == "dirty":
        slot.write_file("README", "changed")
    elif case == "untracked":
        slot.write_file("scratch", "x")
    elif case == "missing":
        repo.drop_checkout(slot.path)
    elif case == "not_listed":
        repo.drop_worktree(slot.path)
    else:
        con.execute("UPDATE reservation SET repo_id='other'")
        con.execute("UPDATE plan_attempt SET repo_id='other'")
    agent = run()
    attempts = body(con, tmp_path, agent, checkouts)
    for _ in range(2):  # nothing moved: the same refusal again
        result = attempts.execute(KEY, ENTRY)
        assert (result.status, result.reason) == (status, reason)
    assert agent.calls == [] and Spy.cleanups == [1, 1]
    assert con.execute("SELECT phase,rev,base_commit FROM plan_attempt").fetchone() == ("admitted", 0, None)
