"""Real layer, the publication's wiring on the real Git adapter: a bare `remote.git` under tmp_path is `origin` (a
`file://` URL) of a person's checkout with one adopted `--detach` slot; the task is admitted, run with a `FakeRun` agent,
verified (X on `task/tl-1`), released, then published through `composition.remotes` (hooks off, bounded transport).
Set-up runs through `git_porcelain.testing`'s runner; nothing leaves tmp_path."""

import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from beads_client import Bead
from beads_client.testing import FakeTaskReadClient
from git_porcelain import Repo
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git
from sqlite_store import begin_immediate

from taskloop.composition import RealSlotFiles, checkouts, remotes
from taskloop.plan import PlanAttempts
from taskloop.plan_admit import AdmitRequest, Admitted, PlanAdmission
from taskloop.plan_files import PlanFiles
from taskloop.plan_publish import AlreadyPublished, BranchPublished, NotPublished, PlanPublish, PublishResult
from taskloop.plan_release import PlanRelease, Released
from taskloop.plan_store import PlanStore
from taskloop.plan_types import AttemptKey, Verified
from taskloop.plan_verifier import PlanVerifier
from taskloop.repo import RepoId
from taskloop.slot_lock import custody, hold, probe
from taskloop.slots import adopt
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task

ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "done"}
TASKS = FakeTaskReadClient([Bead("tl-1", title="Plan it")])
BRANCH = "refs/heads/task/tl-1"


def tasks(task_id: str, backlog: str, tracker_root: str) -> TaskInspection:
    return inspect_task(TaskBinding(TaskScope(backlog), Path(tracker_root)), TASKS, task_id)


def yes(_root: str, _task: str) -> bool:
    return True


def gone(_worker: Worker) -> bool:
    return True


def write_plan(slot: Path) -> Callable[[Harness, LaunchSpec, float, RunHooks | None], RunOutcome]:
    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        (slot / P).parent.mkdir(parents=True)
        (slot / P).write_text("# Plan\n")
        outcome = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), rc=0, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    return run


class Published:
    """A bare origin, the person's checkout and its adopted slot; one task run, verified and released: X."""

    def __init__(self, root: Path, factory: sqlite3.Connection) -> None:
        self.root, self.remote, self.main = root, root / "remote.git", root / "repo"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        (self.main / "README").write_text("one\n")
        git(self.main, "add", "README")
        git(self.main, "commit", "-q", "-m", "base")
        git(self.main, "remote", "add", "origin", self.remote.as_uri())
        git(self.main, "push", "-q", "origin", "main")
        repo_id = RepoId(checkouts(self.main).identity().key)
        self.slot = root / "slots" / repo_id / "s1"
        git(self.main, "worktree", "add", "-q", "--detach", str(self.slot), "HEAD")
        self.d = self.rev(self.slot, "HEAD")
        adopt(lambda: factory, begin_immediate, checkouts(self.main), root / "slots", 1)
        self.store, self.files = PlanStore(lambda: factory), RealSlotFiles()
        admission = PlanAdmission(lambda: factory, begin_immediate, PlanFiles(root / "art"), tasks, checkouts, yes, yes, lambda: 10, probe)
        admitted = admission.admit(AdmitRequest("tl-1", "tasks", str(root), self.main, "m", "high", "workspace-write", 100))
        assert isinstance(admitted, Admitted) and self.store.register_entry(admitted.key, ENTRY, 10) == "accepted"
        self.key: AttemptKey = admitted.key
        attempts = PlanAttempts(self.store, PlanFiles(root / "art"), lambda: ("/bin/codex", {}), write_plan(self.slot), lambda: 10,
                                checkouts, self.files)
        attempts.execute(self.key, ENTRY)
        assert isinstance(PlanVerifier(self.store, checkouts, self.files, gone, lambda: 20, hold).verify(self.key), Verified)
        self.x = self.rev(self.main, BRANCH)
        releaser = PlanRelease(self.store, checkouts, self.files, lambda _entry: "gone", gone, custody, yes, lambda: 30)
        assert isinstance(releaser.release(self.key, False), Released)
        self.opened: list[Path] = []

    @staticmethod
    def rev(where: Path, name: str) -> str:
        return git(where, "rev-parse", name).strip()

    def remote_tip(self) -> str | None:
        found = git(self.remote, "for-each-ref", "--format=%(objectname)", BRANCH).strip()
        return found or None

    def counted(self, path: Path) -> Repo:
        self.opened.append(path)
        return remotes(path)

    def publish(self) -> PublishResult:
        return PlanPublish(self.store, self.counted, self.files, lambda: 40).publish(self.key)

    def other(self, name: str) -> Path:
        """Another clone of origin, as another PC would have."""
        where = self.root / name
        git(self.root, "clone", "-q", self.remote.as_uri(), str(where))
        return where


@pytest.fixture
def real(tmp_path: Path, factory: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> Published:
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    return Published(tmp_path.resolve(), factory)


def test_a_published_plan_is_on_origin_and_the_tracking_ref_and_the_second_call_runs_no_git(real: Published) -> None:
    assert real.publish() == BranchPublished(real.x, real.x)
    assert real.remote_tip() == real.x and real.rev(real.main, "refs/remotes/origin/task/tl-1") == real.x
    assert git(real.slot, "rev-parse", "--abbrev-ref", "HEAD").strip() == "HEAD" and real.rev(real.slot, "HEAD") == real.d
    assert real.slot not in real.opened
    real.opened.clear()
    assert real.publish() == AlreadyPublished(real.x, real.x, 40.0) and real.opened == []


def test_a_commit_pushed_on_top_by_another_clone_is_refused_remote_ahead_and_not_recorded(real: Published) -> None:
    git(real.main, "push", "-q", "origin", f"{real.x}:{BRANCH}")  # published by hand first, then built on elsewhere
    other = real.other("other")
    git(other, "switch", "-q", "task/tl-1")
    (other / "later.md").write_text("more\n")
    git(other, "add", "later.md")
    git(other, "commit", "-q", "-m", "later")
    git(other, "push", "-q", "origin", "task/tl-1")
    t = real.rev(other, "HEAD")
    git(real.main, "fetch", "-q", "origin")
    found = real.publish()
    assert isinstance(found, NotPublished) and (found.kind, found.reason) == ("refused", "remote_ahead") and real.remote_tip() == t
    assert real.store.attempts()[0].published is None  # only a `Pushed` result is recorded


def test_an_unrelated_remote_branch_is_remote_moved_then_diverged_and_never_forced(real: Published) -> None:
    other = real.other("other")
    git(other, "switch", "-q", "--orphan", "task/tl-1")
    git(other, "commit", "-q", "--allow-empty", "-m", "other")
    git(other, "push", "-q", "origin", "task/tl-1")
    t = real.rev(other, "HEAD")
    moved = real.publish()
    assert isinstance(moved, NotPublished) and (moved.kind, moved.reason) == ("refused", "remote_moved")
    git(real.main, "fetch", "-q", "origin", "task/tl-1")
    diverged = real.publish()
    assert isinstance(diverged, NotPublished) and (diverged.kind, diverged.reason) == ("refused", "diverged")
    assert real.remote_tip() == t and str(real.remote) not in moved.detail + diverged.detail


def test_no_origin_is_refused_and_a_missing_remote_path_is_unavailable_remote(real: Published) -> None:
    git(real.main, "remote", "set-url", "origin", (real.root / "missing.git").as_uri())
    missing = real.publish()
    assert isinstance(missing, NotPublished) and (missing.kind, missing.reason) == ("unavailable", "remote")
    assert "missing.git" not in missing.detail
    git(real.main, "remote", "remove", "origin")
    found = real.publish()
    assert isinstance(found, NotPublished) and (found.kind, found.reason) == ("refused", "no_remote") and real.remote_tip() is None


def test_the_repositorys_own_pre_push_hook_never_runs_for_the_factory(real: Published) -> None:
    marker = real.root / "marker"
    hook = Path(git(real.main, "rev-parse", "--git-path", "hooks").strip())
    hook = hook if hook.is_absolute() else real.main / hook
    hook.mkdir(parents=True, exist_ok=True)
    (hook / "pre-push").write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    os.chmod(hook / "pre-push", 0o755)
    assert real.publish() == BranchPublished(real.x, real.x) and not marker.exists()
    git(real.main, "push", "-q", "origin", f"{real.x}:refs/heads/probe")  # a person's own push still runs it
    assert marker.exists()
