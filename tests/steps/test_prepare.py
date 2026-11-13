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
from doubles import Environment, FakeSlotFiles, PinnedViews
from git_porcelain import BranchHeld, GitReadFailure, Recorded, Repo, Sha
from git_porcelain.api import TakeResult
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from sqlite_store import begin_immediate

from taskloop import prepare
from taskloop.admit import AdmitRefused, AdmitRequest, AdmitResult, Admitted, AttemptAdmission
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import TRAILER, AttemptKey, AttemptResult, Checkouts, FileRef, SlotFiles
from taskloop.evidence_files import EvidenceFiles
from taskloop.prepare import UNPUBLISHED, Branch, BranchRefusal, branch_refusal, named
from taskloop.slots import SlotGit, adopt, folder_name
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
    monkeypatch.setattr("taskloop.harness_choice.CodexHarness", CountingHarness)
    monkeypatch.setattr(CountingHarness, "cleanups", [])
    return registered


def head(repo: FakeRepo, path: Path) -> Sha | None:
    return next(worktree.head for worktree in repo.worktrees() if worktree.path == path)


def advance(worktree: FakeWorktree, message: str = "someone's commit") -> Sha:
    worktree.write_file("README", f"moved {worktree.path.name}")
    made = worktree.record(message, paths="all")
    assert isinstance(made, Recorded)
    return made.sha


def leave(repo: FakeRepo, tmp_path: Path, name: str, start: str = "HEAD", *, extra: bool = False, own: bool = True) -> Sha:
    """A branch `name` at `start` (one more commit with `extra`: an earlier attempt's, with its trailer, unless `own` is
    False: the person's), held by no worktree afterwards."""
    other = repo.add_worktree(tmp_path / "other", "HEAD")
    other.checkout_new(name, start)
    tip = advance(other, f"Plan\n\n{TRAILER}: a1" if own else "someone's commit") if extra else head(repo, other.path)
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
    environment = Environment(con, checkouts, tmp_path, tmp_bytes=4096).preparation()  # an implement attempt's setup passes
    result = Attempts(store, EvidenceFiles(tmp_path), lambda: ("/bin/codex", {}), agent, lambda: 10, checkouts, files,
                      environment=environment).execute(KEY, ENTRY, lambda: "held")
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
    """`main` moved on after the slot was parked at D. Absent: created at `main`'s tip, never at D. An existing local
    branch that contains D is checked out as it is; a remote-tracking tip that contains D (and no local branch) is where
    the new branch starts; neither follows `main`. B is the HEAD read on the branch."""
    made = {"local": lambda: leave(repo, tmp_path, BRANCH, extra=True), "remote": lambda: pushed(repo, tmp_path)}
    existing = made[where]() if where in made else None
    moved = on_main(repo)
    tip = existing or moved
    status, reason, agent = execute(con, tmp_path, checkouts, slot_files)
    assert (status, reason, len(agent.calls)) == ("pending", "verification", 1)
    assert slot.branch() == BRANCH and con.execute("SELECT base_commit FROM attempt").fetchone() == (tip,)
    assert dict(repo.branches("task/"))[BRANCH] == head(repo, slot.path)


def test_a_new_branch_without_a_local_main_is_target_and_an_existing_one_needs_none(
    con: sqlite3.Connection, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    d = head(repo, slot.path) or ""
    repo.rename_branch("main", "trunk")
    assert branch_refusal(repo, "tl-1", (d,)) == "target"
    refused_untouched(con, tmp_path, checkouts, slot_files, "target")
    assert slot.branch() is None
    tip = leave(repo, tmp_path, BRANCH, extra=True)
    assert branch_refusal(repo, "tl-1", (d,)) == Branch((d,), tip, None, tip)


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
    return admission.admit(AdmitRequest(task_id, "tasks", str(tmp_path), repo.path, "m", "high", "workspace-write", 100, None)), claims


def slots(factory: sqlite3.Connection, repo: FakeRepo, root: Path, count: int) -> list[FakeWorktree]:
    made = [repo.add_worktree(root.resolve() / folder_name(repo.identity()) / f"s{n}", "HEAD") for n in range(1, count + 1)]
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
    assert (result.slots == () and "not a slot" in result.detail) is (case == "held")  # outside the slots folder: no `adopt` advice
    assert claims.calls == [] and factory.execute("SELECT count(*) FROM attempt").fetchone() == (0,)


def test_a_slot_left_on_the_task_branch_is_named_with_its_fix_while_another_slot_is_free(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    """After a factory.db discard the slot an agent left on `task/<id>` is not free: the refusal names it (an `attached`
    view, which the round log reports `unusable`), the git command that fixes it and `tl slot adopt`, though s2 is free."""
    first, _second = slots(factory, repo, root, 2)
    first.checkout_new(BRANCH)
    result, claims = admitted(factory, repo, root, tmp_path)
    assert isinstance(result, AdmitRefused) and result.reason == "branch_held" and claims.calls == []
    assert [(view.name, view.reason, view.path) for view in result.slots] == [("s1", "attached", first.path)]
    assert "`git switch --detach`" in result.detail and "`tl slot adopt`" in result.detail
    assert f"s1 attached ({first.path})" in result.detail


def test_a_main_checkout_on_the_task_branch_is_named_as_the_persons_to_switch_not_as_a_slot(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    slots(factory, repo, root, 2)
    repo.worktree(repo.identity().root).checkout_new(BRANCH)
    result, claims = admitted(factory, repo, root, tmp_path)
    assert isinstance(result, AdmitRefused) and result.reason == "branch_held" and result.slots == () and claims.calls == []
    assert "your main checkout" in result.detail and "tl slot adopt" not in result.detail and "unusable" not in result.detail


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


def test_with_no_task_branch_a_slot_outside_mains_history_is_skipped_or_diverged(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    """A new branch starts at `main`, which must contain the slot's D (the release parks the slot back there and later
    steps check it): s1 sits at a commit outside `main`'s history, s2 on it."""
    first, second = slots(factory, repo, root, 2)
    advance(first)
    result, _claims = admitted(factory, repo, root, tmp_path)
    assert isinstance(result, Admitted) and result.slot == "s2"
    advance(second)
    result, claims = admitted(factory, repo, root, tmp_path, "tl-2")
    assert isinstance(result, AdmitRefused) and result.reason == "branch_diverged" and "your local main" in result.detail
    assert claims.calls == []


def test_admission_without_a_local_main_is_target_before_its_input_claim_or_rows(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    slots(factory, repo, root, 1)
    repo.rename_branch("main", "trunk")
    result, claims = admitted(factory, repo, root, tmp_path)
    assert isinstance(result, AdmitRefused) and result.reason == "target" and "refs/heads/main" in result.detail
    assert claims.calls == [] and factory.execute("SELECT count(*) FROM attempt").fetchone() == (0,)


def on_main(repo: FakeRepo) -> Sha:
    """X: a commit the slot (detached at D) does not have checked out, made on the person's checkout."""
    return advance(repo.worktree(repo.identity().root))


def detached(checkouts: Checkouts, files: SlotFiles, slot: FakeWorktree, commit: str) -> prepare.Prepared | AttemptResult:
    return prepare.detach_at(checkouts, files, str(slot.path), slot.repo.identity().key, commit)


def test_a_clean_slot_at_d_takes_x_detached_through_its_pinned_view(
    repo: FakeRepo, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles
) -> None:
    x, branches = on_main(repo), repo.branches()
    gitdir = repo.identity().common_dir / "worktrees" / "s1"
    assert detached(checkouts, slot_files, slot, x) == prepare.Prepared(x, gitdir, repo.identity().root)
    assert (head(repo, slot.path), slot.branch()) == (x, None) and repo.branches() == branches
    assert set(checkouts.slot_opens(slot.path)) == {gitdir}


def test_a_slot_already_at_x_passes_in_any_state_without_a_write(
    repo: FakeRepo, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The environment's hard reset makes it exactly X; a relaunch after a killed check finds it so."""
    x = head(repo, slot.path) or ""
    slot.write_file("README", "rewritten by a check")
    monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_options: pytest.fail("no write"))
    found = detached(checkouts, slot_files, slot, x)
    assert isinstance(found, prepare.Prepared) and found.head == x


def test_a_slot_on_a_branch_or_without_x_concludes_and_a_dirty_one_elsewhere_relaunches(
    repo: FakeRepo, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles, monkeypatch: pytest.MonkeyPatch
) -> None:
    x = on_main(repo)
    monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_options: pytest.fail("no write"))
    slot.write_file("README", "left")
    assert detached(checkouts, slot_files, slot, "e" * 40) == AttemptResult("refused", "commit_missing")  # concludes first
    assert detached(checkouts, slot_files, slot, x) == AttemptResult("refused", "slot_dirty")
    slot.checkout_new("task/tl-1")
    assert detached(checkouts, slot_files, slot, x) == AttemptResult("refused", "slot:branch")


def test_a_redirected_pointer_takes_nothing(repo: FakeRepo, slot: FakeWorktree, checkouts: Checkouts, slot_files: FakeSlotFiles) -> None:
    x = on_main(repo)
    slot_files.contents[slot.path / ".git"] = b"gitdir: /elsewhere/.git/worktrees/s1\n"
    assert detached(checkouts, slot_files, slot, x) == AttemptResult("refused", "slot:redirected")
    assert head(repo, slot.path) != x


def test_a_take_that_does_not_land_on_x_detached_is_moved(
    repo: FakeRepo, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles, monkeypatch: pytest.MonkeyPatch
) -> None:
    x = on_main(repo)
    monkeypatch.setattr(FakeWorktree, "park", lambda self, _base, **_options: self.checkout_new("elsewhere"))
    assert detached(checkouts, slot_files, slot, x) == AttemptResult("refused", "slot:moved")


def test_an_unreadable_slot_is_unknown(
    repo: FakeRepo, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles, monkeypatch: pytest.MonkeyPatch
) -> None:
    x = on_main(repo)

    def unreadable(*_args: object) -> bool:
        raise GitReadFailure("history unreadable")

    monkeypatch.setattr(FakeRepo, "is_ancestor", unreadable)  # never `commit_missing`: only a missing revision is
    assert detached(checkouts, slot_files, slot, x) == AttemptResult("unavailable", "git")


def test_a_local_task_branch_with_the_persons_unpublished_commit_is_refused_but_an_attempts_own_resumes(
    repo: FakeRepo, tmp_path: Path
) -> None:
    tip = leave(repo, tmp_path, BRANCH, extra=True, own=False)
    assert branch_refusal(repo, "tl-1", ()) == "branch_unpublished"
    assert "git branch -m task/{task} old/task/{task}" in UNPUBLISHED
    repo.delete_branch(BRANCH, expected=tip)
    leave(repo, tmp_path, BRANCH, extra=True)  # an abandoned attempt's own commit (trailer): resumed as before
    assert isinstance(branch_refusal(repo, "tl-1", ()), Branch)
