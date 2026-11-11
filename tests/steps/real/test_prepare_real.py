"""Real layer, one wiring row of slot preparation on the real Git adapter: a person's `--detach` slot is adopted at D,
`main` moves on, the task is admitted (the branch rule's real `for-each-ref`, worktree listing and ancestry reads), the
attempt takes `task/tl-1` at `main`'s new tip M, not at D, with real `take_branch` on the slot's hardened view, the
agent writes its plan, and the verify (under the real slot lock) commits X on the branch: verified, the branch tip is
X. Set-up runs through `git_porcelain.testing`'s runner under tmp_path."""

import json
import sqlite3
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from beads_client import Bead
from beads_client.testing import FakeTaskReadClient
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git
from sqlite_store import begin_immediate

from taskloop.admit import AdmitRequest, Admitted, AttemptAdmission
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Verified
from taskloop.evidence_files import EvidenceFiles
from taskloop.git_views import checkouts
from taskloop.slot_files import RealSlotFiles
from taskloop.slot_lock import hold, lock_path, probe
from taskloop.slots import SlotGit, adopt
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task
from taskloop.verifier import Verifier

ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "done"}
TASKS = FakeTaskReadClient([Bead("tl-1", title="Plan it")])


def tasks(task_id: str, backlog: str, tracker_root: str) -> TaskInspection:
    return inspect_task(TaskBinding(TaskScope(backlog), Path(tracker_root)), TASKS, task_id)


def claimed(_root: str, _task: str) -> bool:
    return True


def test_a_detached_slot_is_prepared_on_its_task_branch_and_the_plan_is_committed_there(
    tmp_path: Path, factory: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    main, slots, art = root / "repo", root / "slots", root / "art"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "README").write_text("one\n")
    git(main, "add", "README")
    git(main, "commit", "-q", "-m", "base")
    slot = slots / checkouts(main).identity().key / "s1"
    git(main, "worktree", "add", "-q", "--detach", str(slot), "HEAD")
    d = git(slot, "rev-parse", "HEAD").strip()
    adopt(lambda: factory, begin_immediate, checkouts(main), SlotGit(checkouts, RealSlotFiles()), slots, 1)
    (main / "README").write_text("two\n")
    git(main, "commit", "-q", "-am", "main moves on")
    m = git(main, "rev-parse", "HEAD").strip()
    admission = AttemptAdmission(
        lambda: factory, begin_immediate, EvidenceFiles(art), tasks, checkouts, claimed, claimed, lambda: 10, probe, RealSlotFiles()
    )
    admitted = admission.admit(AdmitRequest("tl-1", "tasks", str(root), main, "m", "high", "workspace-write", 100))
    assert isinstance(admitted, Admitted) and admitted.slot == "s1"
    store, files = AttemptStore(lambda: factory), RealSlotFiles()
    assert store.register_entry(admitted.key, ENTRY, 10) == "accepted"

    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert git(slot, "symbolic-ref", "--short", "HEAD").strip() == "task/tl-1"  # the agent starts on the branch, at M
        assert git(slot, "rev-parse", "HEAD").strip() == m and (slot / "README").read_text() == "two\n"
        (slot / P).parent.mkdir(parents=True)
        (slot / P).write_text("# Plan\n")
        outcome = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), rc=0, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    attempts = Attempts(store, EvidenceFiles(art), lambda: ("/bin/codex", {}), run, lambda: 10, checkouts, files)
    assert attempts.execute(admitted.key, ENTRY).reason == "verification"
    verdict = Verifier(store, checkouts, files, lambda _worker: True, lambda: 20, hold).verify(admitted.key)
    assert isinstance(verdict, Verified) and not verdict.reused
    x = git(slot, "rev-parse", "HEAD").strip()
    assert git(main, "rev-parse", "refs/heads/task/tl-1").strip() == x and git(slot, "rev-parse", "HEAD^").strip() == m != d
    assert git(slot, "status", "--porcelain").strip() == "" and lock_path(str(slot)).is_file()
