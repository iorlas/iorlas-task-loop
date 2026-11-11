"""The task branch rule and the slot's preparation onto `task/<id>`: at admission before anything is held, and at the
entry right before dispatch. Real SQLite, the semantic Git fake with its fake remote (origin's remote-tracking refs come
from a fetch), the owning agent and task-read fakes."""

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal, Protocol

import pytest
from any_agent import CodexHarness, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from beads_client import Bead
from beads_client.testing import FakeTaskReadClient
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain import BranchHeld, GitReadFailure, Recorded, Repo, Sha
from git_porcelain.api import TakeResult
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from sqlite_store import begin_immediate

from taskloop import prepare
from taskloop.admit import AdmitRefused, AdmitRequest, AdmitResult, Admitted, AttemptAdmission
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, FileRef, SlotFiles
from taskloop.evidence_files import EvidenceFiles
from taskloop.prepare import Branch, BranchRefusal, branch_refusal, named
from taskloop.slots import SlotGit, adopt
from taskloop.task import TaskBinding, TaskInspection, TaskScope
from taskloop.tracker import inspect_task

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "Plan written"}
BRANCH = "task/tl-1"


class CountingHarness(CodexHarness):
    cleanups: ClassVar[list[int]] = []

    def cleanup(self) -> None:
        CountingHarness.cleanups.append(1)
        super().cleanup()


@pytest.fixture
def remote() -> FakeRemote:
    found = FakeRemote("https://example.invalid/repo.git")
    found.advance("main", {"README": "one"})
    return found


@pytest.fixture
def repo(tmp_path: Path, remote: FakeRemote) -> FakeRepo:
    """The conftest's clone, with its remote in reach."""
    return FakeRepo.clone(remote, tmp_path / "main")


@pytest.fixture
def con(registered: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setattr("taskloop.attempt.CodexHarness", CountingHarness)
    monkeypatch.setattr(CountingHarness, "cleanups", [])
    return registered


def head(repo: FakeRepo, path: Path) -> Sha | None:
    return next(worktree.head for worktree in repo.worktrees() if worktree.path == path)


def advance(worktree: FakeWorktree) -> Sha:
    worktree.write_file("README", f"moved {worktree.path.name}")
    made = worktree.record("someone's commit", paths="all")
    assert isinstance(made, Recorded)
    return made.sha


def leave(repo: FakeRepo, tmp_path: Path, name: str, start: str = "HEAD", *, extra: bool = False) -> Sha:
    """A person's branch `name` at `start` (one more commit with `extra`), held by no worktree afterwards."""
    other = repo.add_worktree(tmp_path / "other", "HEAD")
    other.checkout_new(name, start)
    tip = advance(other) if extra else head(repo, other.path)
    other.park("HEAD")
    repo.drop_worktree(other.path)
    assert tip is not None
    return tip


def pushed(repo: FakeRepo, tmp_path: Path) -> Sha:
    """origin's `task/tl-1`, one commit on the current HEAD, fetched as a remote-tracking ref with no local branch."""
    other = repo.add_worktree(tmp_path / "pusher", "HEAD")
    other.checkout_new(BRANCH)
    tip = advance(other)
    other.push(BRANCH)
    other.park("HEAD")
    repo.drop_worktree(other.path)
    repo.delete_branch(BRANCH, expected=tip)
    assert repo.refs(["refs/heads/task", "refs/remotes/origin/task"])[0].name == "refs/remotes/origin/task/tl-1"
    return tip


def execute(con: sqlite3.Connection, tmp_path: Path, checkouts: Checkouts, files: SlotFiles) -> tuple[str, str, FakeRun]:
    agent = FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), rc=0, stands=True)))
    store = AttemptStore(lambda: con)
    result = Attempts(store, EvidenceFiles(tmp_path), lambda: ("/bin/codex", {}), agent, lambda: 10, checkouts, files).execute(KEY, ENTRY)
    return result.status, result.reason, agent


@pytest.mark.parametrize(
    ("task_id", "ok"),
    [("tl-1", True), ("tl-8bh9.4.3.1.10", True), ("A_b-9", True), ("", False), ("a/b", False), ("a b", False),
     ("a~1", False), ("a^", False), ("a:b", False), ("a?", False), ("a*", False), ("a[", False), ("a\\b", False),
     ("a\n", False), (".a", False), ("-a", False), ("a..b", False), ("a.", False), ("a.lock", False), ("tl-é", False)],
)
def test_the_name_rule_reads_no_git(repo: FakeRepo, monkeypatch: pytest.MonkeyPatch, task_id: str, ok: bool) -> None:
    assert named(task_id) is ok
    if not ok:
        for read in ("refs", "worktrees", "is_ancestor"):
            monkeypatch.setattr(repo, read, lambda *_args, **_kwargs: pytest.fail("a Git read"))
        assert branch_refusal(repo, task_id, ("d",)) == "branch_name"


@pytest.mark.parametrize("name", ["task", "task/tl-1/x", "task/TL-1"])
def test_a_ref_that_collides_with_the_branch_is_branch_name(repo: FakeRepo, tmp_path: Path, name: str) -> None:
    leave(repo, tmp_path, name)
    assert branch_refusal(repo, "tl-1", (head(repo, repo.path) or "",)) == "branch_name"


@pytest.mark.parametrize("where", ["absent", "local", "remote"])
def test_attempt_one_takes_its_branch_and_starts_from_what_it_holds(
    con: sqlite3.Connection, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles,
    where: Literal["absent", "local", "remote"],
) -> None:
    """Absent: created at D. An existing local branch that contains D is checked out as it is; a remote-tracking tip that
    contains D (and no local branch) is where the new branch starts. B is the HEAD read on the branch."""
    d = head(repo, slot.path)
    made = {"local": lambda: leave(repo, tmp_path, BRANCH, extra=True), "remote": lambda: pushed(repo, tmp_path)}
    tip = made[where]() if where in made else d
    status, reason, agent = execute(con, tmp_path, checkouts, slot_files)
    assert (status, reason, len(agent.calls)) == ("pending", "verification", 1)
    assert slot.branch() == BRANCH and con.execute("SELECT base_commit FROM attempt").fetchone() == (tip,)
    assert dict(repo.branches("task/"))[BRANCH] == head(repo, slot.path)


def test_a_slot_already_on_its_branch_takes_nothing(
    con: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash after the branch was taken, before dispatch: the relaunched entry finds the slot on it, writes no Git."""
    slot.checkout_new(BRANCH)
    taken: list[str] = []

    def take(self: FakeWorktree, branch: str, base: str, **_options: object) -> TakeResult:
        taken.append(branch)
        raise AssertionError("no Git write")

    monkeypatch.setattr(FakeWorktree, "take_branch", take)
    assert execute(con, tmp_path, checkouts, slot_files)[:2] == ("pending", "verification") and taken == []


@pytest.mark.parametrize("where", ["local", "remote"])
def test_a_tip_without_the_slots_commit_is_diverged_and_nothing_runs(
    con: sqlite3.Connection, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles,
    where: str,
) -> None:
    """The old factory's `task/<id>` from elsewhere: refused, never resumed or overwritten (the person renames it)."""
    tip = leave(repo, tmp_path, BRANCH) if where == "local" else pushed(repo, tmp_path)
    d = advance(slot)  # the slot moved on: the old tip lacks D
    assert branch_refusal(repo, "tl-1", (d,)) == "branch_diverged"
    for _ in range(2):  # nothing moved: the same refusal again
        status, reason, agent = execute(con, tmp_path, checkouts, slot_files)
        assert (status, reason, agent.calls) == ("refused", "branch_diverged", [])
    assert CountingHarness.cleanups == [1, 1] and slot.branch() is None and dict(repo.branches("task/")).get(BRANCH) in (tip, None)
    assert con.execute("SELECT phase,rev,base_commit FROM attempt").fetchone() == ("admitted", 0, None)


@pytest.mark.parametrize(("where", "contains"), [
    ("local", True), ("remote", True), ("local", False), ("remote", False), ("gone", False), ("both", False),
])
def test_attempt_one_of_a_later_step_needs_the_previous_steps_commit_on_its_branch(
    con: sqlite3.Connection, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles,
    where: str, contains: bool,
) -> None:
    """The tip the slot would take (local, else remote-tracking) must contain `after_commit`; someone reset the branch
    after the previous step, or its commit is gone: `branch_moved`, nothing taken, the slot still detached."""
    tip = pushed(repo, tmp_path) if where in ("remote", "both") else leave(repo, tmp_path, BRANCH, extra=contains)
    if where == "both":  # a local branch at D beside origin's tip, which holds X: the local one is what the slot takes
        leave(repo, tmp_path, BRANCH)
    after = tip if contains or where == "both" else "f" * 40 if where == "gone" else leave(repo, tmp_path, "elsewhere", extra=True)
    con.execute("UPDATE attempt SET step='implement',after_commit=?", (after,))
    status, reason, agent = execute(con, tmp_path, checkouts, slot_files)
    if contains:
        assert len(agent.calls) == 1 and slot.branch() == BRANCH
    else:
        assert (status, reason, agent.calls, slot.branch()) == ("refused", "branch_moved", [], None)
        assert con.execute("SELECT phase,base_commit FROM attempt").fetchone() == ("admitted", None)


def test_an_unreadable_branch_is_unknown_never_absent(
    con: sqlite3.Connection, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refs(_prefixes: Sequence[str]) -> tuple[()]:
        raise GitReadFailure("for-each-ref failed")

    monkeypatch.setattr(repo, "refs", refs)
    status, reason, agent = execute(con, tmp_path, checkouts, slot_files)
    assert (status, reason, agent.calls, CountingHarness.cleanups) == ("unavailable", "git", [], [1]) and slot.branch() is None


class PointerFiles(SlotFiles, Protocol):
    contents: dict[Path, bytes]


def refused_untouched(con: sqlite3.Connection, tmp_path: Path, checkouts: Checkouts, files: SlotFiles, word: str) -> None:
    status, reason, agent = execute(con, tmp_path, checkouts, files)
    assert (status, reason, agent.calls, CountingHarness.cleanups) == ("refused", word, [], [1])
    assert con.execute("SELECT phase,rev,base_commit FROM attempt").fetchone() == ("admitted", 0, None)


def test_a_pointer_rewritten_after_the_rule_is_redirected_before_the_take(
    con: sqlite3.Connection, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: PointerFiles,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = prepare.branch_refusal

    def ruled(git: Repo, task_id: str, heads: Sequence[str]) -> BranchRefusal | Branch:
        found = rule(git, task_id, heads)
        slot_files.contents[slot.path / ".git"] = b"gitdir: /elsewhere/.git/worktrees/s1\n"
        return found

    monkeypatch.setattr(prepare, "branch_refusal", ruled)
    monkeypatch.setattr(FakeWorktree, "take_branch", lambda *_args, **_options: pytest.fail("a Git write"))
    refused_untouched(con, tmp_path, checkouts, slot_files, "slot_redirected")


def test_a_branch_checked_out_elsewhere_during_the_take_is_held(
    con: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(FakeWorktree, "take_branch", lambda *_args, **_options: BranchHeld(()))
    refused_untouched(con, tmp_path, checkouts, slot_files, "branch_held")
    assert slot.branch() is None


def test_a_branch_without_d_made_during_the_take_is_diverged_and_the_slot_parked_back(
    con: sqlite3.Connection, repo: FakeRepo, remote: FakeRemote, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts,
    slot_files: SlotFiles, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resume` checks an existing branch out as it is: one made after the rule ran is found without D after the take;
    the slot goes back to D, detached, so the next entry refuses it again instead of starting from that tip."""
    d = head(repo, slot.path)
    remote.advance("elsewhere", {"old": "factory"})  # an unrelated history
    repo.fetch()
    take = FakeWorktree.take_branch

    def racing(self: FakeWorktree, branch: str, base: str, **options: Literal["resume"]) -> TakeResult:
        leave(repo, tmp_path, BRANCH, "refs/remotes/origin/elsewhere")
        return take(self, branch, base, **options)

    monkeypatch.setattr(FakeWorktree, "take_branch", racing)
    refused_untouched(con, tmp_path, checkouts, slot_files, "branch_diverged")
    assert (slot.branch(), head(repo, slot.path)) == (None, d)
    monkeypatch.setattr(FakeWorktree, "take_branch", take)
    assert execute(con, tmp_path, checkouts, slot_files)[:2] == ("refused", "branch_diverged")


def test_a_branch_moved_off_the_previous_commit_during_the_take_is_parked_back(
    con: sqlite3.Connection, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule saw `task/<id>` holding X; someone reset it to D before the take: the slot goes back to D, detached."""
    d, x = head(repo, slot.path), leave(repo, tmp_path, BRANCH, extra=True)
    con.execute("UPDATE attempt SET step='implement',after_commit=?", (x,))
    take = FakeWorktree.take_branch

    def racing(self: FakeWorktree, branch: str, base: str, **options: Literal["resume"]) -> TakeResult:
        repo.delete_branch(BRANCH, expected=x)
        leave(repo, tmp_path / "reset", BRANCH)
        return take(self, branch, base, **options)

    monkeypatch.setattr(FakeWorktree, "take_branch", racing)
    refused_untouched(con, tmp_path, checkouts, slot_files, "branch_moved")
    assert (slot.branch(), head(repo, slot.path)) == (None, d)


def test_a_relaunch_on_its_branch_without_the_previous_commit_is_branch_moved(
    con: sqlite3.Connection, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """Attempt 1 relaunched after its branch was taken: the slot is already on `task/<id>`, which lacks X."""
    x = leave(repo, tmp_path, "elsewhere", extra=True)
    con.execute("UPDATE attempt SET step='implement',after_commit=?", (x,))
    slot.checkout_new(BRANCH)
    status, reason, agent = execute(con, tmp_path, checkouts, slot_files)
    assert (status, reason, agent.calls) == ("refused", "branch_moved", [])


class Claims:
    """The claim double and the input writer, recording what admission did."""

    def __init__(self, artifacts: Path) -> None:
        self.calls: list[str] = []
        self.files = self.Files(artifacts, self.calls)

    class Files(EvidenceFiles):
        def __init__(self, root: Path, calls: list[str]) -> None:
            super().__init__(root)
            self.calls = calls

        def put_input(self, key: AttemptKey, text: str) -> FileRef:
            self.calls.append("input")
            return super().put_input(key, text)

    def claim(self, _root: str, task_id: str) -> bool:
        self.calls.append("claim:" + task_id)
        return True

    def unclaim(self, _root: str, task_id: str) -> bool:
        self.calls.append("unclaim:" + task_id)
        return True


def admitted(factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, task_id: str = "tl-1") -> tuple[AdmitResult, Claims]:
    client = FakeTaskReadClient([Bead(task_id, title="Plan it")])

    def tasks(task: str, backlog: str, tracker_root: str) -> TaskInspection:
        return inspect_task(TaskBinding(TaskScope(backlog), Path(tracker_root)), client, task)

    claims = Claims(tmp_path / "artifacts")
    admission = AttemptAdmission(lambda: factory, begin_immediate, claims.files, tasks, PinnedViews(repo),
                              claims.claim, claims.unclaim, lambda: 10, lambda _slot_path: True, FakeSlotFiles(repo))
    return admission.admit(AdmitRequest(task_id, "tasks", str(tmp_path), repo.path, "m", "high", "workspace-write", 100)), claims


def slots(factory: sqlite3.Connection, repo: FakeRepo, root: Path, count: int) -> list[FakeWorktree]:
    made = [repo.add_worktree(root.resolve() / repo.identity().key / f"s{n}", "HEAD") for n in range(1, count + 1)]
    adopt(lambda: factory, begin_immediate, repo, SlotGit(PinnedViews(repo), FakeSlotFiles(repo)), root, count)
    return made


@pytest.mark.parametrize("case", ["name", "held", "diverged"])
def test_admission_refuses_a_branch_before_its_input_claim_or_rows(
    factory: sqlite3.Connection, repo: FakeRepo, remote: FakeRemote, root: Path, tmp_path: Path, case: str
) -> None:
    slots(factory, repo, root, 1)
    if case == "held":
        repo.add_worktree(tmp_path / "elsewhere", "HEAD").checkout_new(BRANCH)
    elif case == "diverged":
        remote.advance(BRANCH, {"old": "factory"})  # an unrelated history
        repo.fetch()
    result, claims = admitted(factory, repo, root, tmp_path, "tl..1" if case == "name" else "tl-1")
    assert isinstance(result, AdmitRefused) and result.reason == f"branch_{case}"
    assert ("git branch -m task/tl-1 old/task/tl-1" in result.detail) is (case == "diverged")
    assert claims.calls == [] and factory.execute("SELECT count(*) FROM attempt").fetchone() == (0,)


def test_admission_skips_a_free_slot_whose_head_the_branch_does_not_contain(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    first, _second = slots(factory, repo, root, 2)
    leave(repo, tmp_path, BRANCH)
    advance(first)  # s1's D is beyond the branch; s2's is on it
    result, claims = admitted(factory, repo, root, tmp_path)
    assert isinstance(result, Admitted) and result.slot == "s2" and claims.calls == ["input", "claim:tl-1"]
    found = branch_refusal(repo, "tl-1", (head(repo, first.path) or "",))
    assert found == "branch_diverged" and isinstance(branch_refusal(repo, "tl-1", ()), Branch)
