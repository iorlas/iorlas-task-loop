"""Real layer, the release's wiring on the real Git adapter under the real slot lock: a person's `--detach` slot is adopted,
the task admitted, run with a `FakeRun` agent and verified (X on `task/tl-1`); the release parks the slot back at D with
real `checkout --detach`, the branch keeps X and the slot is free again. Abandoned instead, the task is admitted afresh and
its entry resumes `task/tl-1` at X through the real branch rule and `take_branch`. Set-up runs through
`git_porcelain.testing`'s runner under tmp_path."""

import json
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from beads_client import Bead
from beads_client.testing import FakeTaskReadClient
from git_porcelain.history import Identity
from git_porcelain.testing import apply_hermetic_env, git
from plan_fixtures import PLAN_TEXT
from sqlite_store import begin_immediate

from taskloop.admit import AdmitRequest, Admitted, AttemptAdmission
from taskloop.agents.launch import AgentLaunch
from taskloop.agents.settings import AgentSetting, CodexPolicy
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS, AttemptKey, Verified
from taskloop.evidence_files import EvidenceFiles
from taskloop.git_views import GitViews
from taskloop.ids import NativeIds
from taskloop.repo import RepoId
from taskloop.slot_files import RealSlotFiles
from taskloop.slot_lock import custody, hold, probe
from taskloop.slot_release import Released, SlotRelease
from taskloop.slots import Adopted, NotAdopted, SlotGit, adopt, folder_name, observe
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task
from taskloop.verifier import Verifier

VIEWS = GitViews(DEFAULT_GIT_READ_SECONDS)

ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "done"}
TASKS = FakeTaskReadClient([Bead("tl-1", title="Plan it")])
type Agent = Callable[[Harness, LaunchSpec, float, RunHooks | None], RunOutcome]


def tasks(task_id: str, backlog: str, tracker_root: str) -> TaskInspection:
    return inspect_task(TaskBinding(TaskScope(backlog), Path(tracker_root)), TASKS, task_id)


def yes(_root: str, _task: str) -> bool:
    return True


def gone(_worker: Worker) -> bool:
    return True


def answered(answer: Mapping[str, object], before: Callable[[], None]) -> Agent:
    def run(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        before()
        outcome = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(answer), rc=0, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    return run


class Repository:
    """A real repository with one adopted `--detach` slot, its factory.db, admission and release."""

    def __init__(self, root: Path, factory: sqlite3.Connection) -> None:
        self.main, self.art, self.factory = root / "repo", root / "art", factory
        self.main.mkdir()
        git(self.main, "init", "-q", "-b", "main")
        (self.main / "README").write_text("one\n")
        (self.main / ".task-loop.json").write_text("{}")
        git(self.main, "add", "README", ".task-loop.json")
        git(self.main, "commit", "-q", "-m", "base")
        slots = root / "slots"
        self.repo_id = RepoId(VIEWS.checkouts(self.main).identity().key)
        self.slot = slots / folder_name(VIEWS.checkouts(self.main).identity()) / "s1"
        git(self.main, "worktree", "add", "-q", "--detach", str(self.slot), "HEAD")
        self.d = self.rev("HEAD")
        adopt(lambda: factory, begin_immediate, VIEWS.checkouts(self.main), SlotGit(VIEWS.checkouts, RealSlotFiles()), slots, 1)
        self.store, self.files = AttemptStore(lambda: factory), RealSlotFiles()
        self.releaser = SlotRelease(self.store, VIEWS.checkouts, self.files, lambda _entry: "gone", gone, custody, yes, lambda: 30,
                                    lambda _setup: "gone", lambda _scratch: True, ids=NativeIds())
        self.admission = AttemptAdmission(
            lambda: factory, begin_immediate, EvidenceFiles(self.art), tasks, VIEWS.checkouts, yes, yes, lambda: 10, probe, RealSlotFiles()
        , ids=NativeIds())
        self.root = root

    def rev(self, name: str) -> str:
        return git(self.slot, "rev-parse", name).strip()

    def run(self, agent: Agent) -> AttemptKey:
        """Admit the task, register its entry, run the attempt once."""
        admitted = self.admission.admit(
            AdmitRequest(
                "tl-1",
                "tasks",
                str(self.root),
                self.main,
                AgentSetting(model="m", effort="high", access=CodexPolicy(sandbox="workspace-write")),
                100,
                None,
            )
        )
        assert isinstance(admitted, Admitted) and admitted.slot == "s1"
        assert self.store.register_entry(admitted.key, ENTRY, 10) == "accepted"
        attempts = Attempts(
            self.store,
            EvidenceFiles(self.art),
            AgentLaunch(lambda _harness: ("/bin/codex", {}), ids=NativeIds()),
            agent,
            lambda: 10,
            VIEWS.checkouts,
            self.files,
        )
        attempts.execute(admitted.key, ENTRY)
        return admitted.key

    def planned(self) -> tuple[AttemptKey, str]:
        def write() -> None:
            (self.slot / P).parent.mkdir(parents=True)
            (self.slot / P).write_text(PLAN_TEXT)

        key = self.run(answered(PLAN, write))
        assert isinstance(Verifier(self.store, VIEWS.checkouts, self.files, gone, lambda: 20, hold, ids=NativeIds()).verify(key), Verified)
        return key, self.rev("HEAD")


@pytest.fixture
def real(tmp_path: Path, factory: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> Repository:
    apply_hermetic_env(monkeypatch, identity=Identity("Person", "person@example.invalid"), config={})
    return Repository(tmp_path.resolve(), factory)


def test_a_verified_slot_is_parked_at_d_detached_and_clean_and_is_free_again(real: Repository) -> None:
    key, x = real.planned()
    assert real.releaser.release(key, False) == Released("s1", real.d, True, "kept", False)
    assert git(real.slot, "rev-parse", "--abbrev-ref", "HEAD").strip() == "HEAD"  # detached
    assert (real.rev("HEAD"), real.rev("refs/heads/task/tl-1")) == (real.d, x)
    assert git(real.slot, "status", "--porcelain").strip() == ""
    views = observe(real.factory, VIEWS.checkouts(real.main), SlotGit(VIEWS.checkouts, RealSlotFiles()), real.repo_id, probe)
    assert [(view.name, view.state) for view in views] == [("s1", "free")]


def test_after_an_abandon_a_fresh_attempt_resumes_the_task_branch_at_x(real: Repository) -> None:
    key, x = real.planned()
    assert real.releaser.release(key, True) == Released("s1", real.d, True, "unclaimed", True)
    seen: list[tuple[str, str]] = []

    def look() -> None:
        seen.append((git(real.slot, "symbolic-ref", "--short", "HEAD").strip(), real.rev("HEAD")))

    unchanged = {"disposition": "unchanged", "plan_path": P, "paths": [], "message": None, "explanation": "still valid"}
    fresh = real.run(answered(unchanged, look))
    assert fresh.reservation_generation == 2 and seen == [("task/tl-1", x)]  # resumed as it is, the committed plan kept


def test_a_slot_whose_pointer_names_another_git_directory_is_never_free_nor_adopted(real: Repository) -> None:
    """Real Git and the real slot file port: a free slot's `.git` rewritten to a Git directory of the agent's making is
    `unknown(redirected)`, and a person's new worktree so rewritten is refused at adoption."""
    fake, slots = real.root / "fake", SlotGit(VIEWS.checkouts, RealSlotFiles())
    git(real.root, "init", "-q", "--bare", str(fake))
    (real.slot / ".git").write_text(f"gitdir: {fake}\n")
    views = observe(real.factory, VIEWS.checkouts(real.main), slots, real.repo_id, probe)
    assert [(view.name, view.state, view.reason) for view in views] == [("s1", "unknown", "redirected")]
    s2 = real.slot.parent / "s2"
    git(real.main, "worktree", "add", "-q", "--detach", str(s2), "HEAD")
    (s2 / ".git").write_text(f"gitdir: {fake}\n")
    found = adopt(lambda: real.factory, begin_immediate, VIEWS.checkouts(real.main), slots, real.slot.parent.parent, 2)
    assert found == (Adopted("s1", real.slot), NotAdopted("s2", "redirected", s2))
