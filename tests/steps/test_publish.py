"""Publication over the in-memory factory.db, the semantic Git fake and its fake remote, the fake slot file port and a fake
clock: what a publish pushes and records, every precondition refused before any push, the rejected-push classification,
the push results the fake cannot produce (a scripted worktree), the fence lost during the push, and a failed record."""

import json
import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import override

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from doubles import FakeSlotFiles
from git_porcelain import GitTimeout, GitUnavailable, HookRejected, MissingRemote, RefRejected, Rejected, RemoteRejected, Repo, Sha
from git_porcelain.api import PushResult
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree

from taskloop.attempt import Attempts
from taskloop.attempt_reads import PublishedRow
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, FileStat, SlotFiles
from taskloop.evidence_files import EvidenceFiles
from taskloop.publish import BranchPublish, BranchPublished, NotPublished, PublishResult, publish_word
from taskloop.slot_release import Released, SlotRelease
from taskloop.verifier import Verifier

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
BRANCH = "refs/heads/task/tl-1"


class ScriptedPushRepo(FakeRepo):
    """The fake clone whose worktrees push through a script: `during` runs as the push starts (another writer meanwhile),
    `answer` replaces the push's result (or is raised), `origin` False makes `origin` absent, and `unreadable` (a sha and an
    error) makes any ancestry read naming that sha raise."""

    during: Callable[[], object] = staticmethod(lambda: None)
    answer: PushResult | GitUnavailable | None = None
    origin: bool = True
    unreadable: tuple[str, GitUnavailable] | None = None

    @override
    def worktree(self, path: Path) -> FakeWorktree:
        return Pushing(self, path)

    @override
    def is_ancestor(self, a: str, b: str) -> bool:
        if self.unreadable is not None and self.unreadable[0] in (a, b):
            raise self.unreadable[1]
        return super().is_ancestor(a, b)

    @override
    def remote_url(self, remote: str) -> str:
        if not self.origin:
            raise MissingRemote(f"error: No such remote '{remote}'")
        return super().remote_url(remote)


class Pushing(FakeWorktree):
    def __init__(self, repo: ScriptedPushRepo, path: Path) -> None:
        super().__init__(repo, path)
        self.script = repo

    @override
    def push(self, dst: str, *, remote: str = "origin", hook_env: object = None, head: Sha | None = None) -> PushResult:
        self.script.during()
        answer = self.script.answer
        if isinstance(answer, GitUnavailable):
            raise answer
        return answer if answer is not None else super().push(dst, remote=remote, head=head)


@pytest.fixture
def remote(request: pytest.FixtureRequest) -> FakeRemote:
    """origin; `indirect` parametrization adds files to main's first commit (a plan already at D)."""
    found = FakeRemote("https://example.invalid/repo.git")
    found.advance("main", {"README": "one", **getattr(request, "param", {})})
    return found


@pytest.fixture
def repo(tmp_path: Path, remote: FakeRemote) -> ScriptedPushRepo:
    return ScriptedPushRepo.clone(remote, tmp_path / "main")


class Observed:
    """The publication's Git views, each open recorded by path."""

    def __init__(self, checkouts: Checkouts) -> None:
        self.checkouts, self.opened = checkouts, list[Path]()

    def __call__(self, path: Path, /, *, git_dir: Path | None = None) -> Repo:
        self.opened.append(path)
        return self.checkouts(path, git_dir=git_dir)


def agent(slot: FakeWorktree, files: dict[str, str], disposition: str = "planned") -> Callable[..., RunOutcome]:
    answer = {"disposition": disposition, "plan_path": P, "paths": list(files), "message": "Plan" if files else None,
              "explanation": "done"}

    def call(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        for path, text in files.items():
            slot.write_file(path, text)
        outcome = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(answer), rc=0, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    return call


@contextmanager
def nothing() -> Generator[None]:
    yield


def nowhere(*_args: object) -> AbstractContextManager[None]:
    return nothing()


def run(con: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, files: SlotFiles,
        written: dict[str, str], disposition: str = "planned", *, verify: bool = True, release: bool = True) -> str:
    """The registered attempt run once on `task/tl-1`, verified and released (settled): the branch tip."""
    store = AttemptStore(lambda: con)
    attempts = Attempts(store, EvidenceFiles(tmp_path), lambda: ("/bin/codex", {}), agent(slot, written, disposition), lambda: 10,
                            checkouts, files)
    assert attempts.execute(KEY, ENTRY).reason == "verification"
    if verify:
        Verifier(store, checkouts, files, lambda _w: True, lambda: 20, nowhere).verify(KEY)
    if release:
        releaser = SlotRelease(store, checkouts, files, lambda _e: "gone", lambda _w: True, nowhere, lambda _r, _t: True, lambda: 30,
                               lambda _setup: "gone", lambda _scratch: True)
        assert isinstance(releaser.release(KEY, False), Released)
    return tip(slot.repo)


def tip(repo: FakeRepo, prefix: str = "refs/heads/task/") -> str:
    return next(ref.sha for ref in repo.refs([prefix]) if ref.name in (BRANCH, "refs/remotes/origin/task/tl-1"))


def publisher(con: sqlite3.Connection, git: Checkouts, files: SlotFiles, store: AttemptStore | None = None) -> BranchPublish:
    return BranchPublish(store or AttemptStore(lambda: con), git, files, lambda: 40)


def rows(con: sqlite3.Connection) -> list[tuple[object, ...]]:
    return con.execute("SELECT attempt_id,commit_sha,remote_head,published_at FROM published_branch").fetchall()


def test_a_verified_released_plan_is_pushed_from_the_checkout_and_recorded_once(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, repo: ScriptedPushRepo, remote: FakeRemote, checkouts: Checkouts,
    slot_files: SlotFiles,
) -> None:
    x = run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    registered.execute("INSERT INTO reservation VALUES ('s1',?,2,'other')", (repo.identity().key,))  # taken again
    git = Observed(checkouts)
    found = publisher(registered, git, slot_files).publish(KEY)
    assert found == BranchPublished(x, x) and publish_word(found) == "published"
    assert remote.branches()["task/tl-1"] == x and tip(repo, "refs/remotes/origin/task/") == x
    assert rows(registered) == [("attempt", x, x, 40.0)] and slot.path not in git.opened and set(git.opened) == {repo.path}
    again = Observed(checkouts)
    remote.offline = True  # no network is needed for an answer already recorded
    assert publisher(registered, again, slot_files).publish(KEY) == PublishedRow(x, x, 40.0) and again.opened == []


@pytest.mark.parametrize("remote", [{P: "# Plan\n"}], indirect=True)
def test_a_reused_plan_publishes_b(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, remote: FakeRemote, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    b = run(registered, tmp_path, slot, checkouts, slot_files, {}, "unchanged")
    assert publisher(registered, checkouts, slot_files).publish(KEY) == BranchPublished(b, b) and remote.branches()["task/tl-1"] == b


def abandoned(con: sqlite3.Connection, _slot: FakeWorktree, _repo: ScriptedPushRepo, _files: FakeSlotFiles) -> None:
    con.execute("UPDATE slot_release SET claim='unclaimed'")


def unverified(con: sqlite3.Connection, _slot: FakeWorktree, _repo: ScriptedPushRepo, _files: FakeSlotFiles) -> None:
    con.execute("DELETE FROM verification")


def redirected(_con: sqlite3.Connection, slot: FakeWorktree, _repo: ScriptedPushRepo, files: FakeSlotFiles) -> None:
    files.entries[slot.path / ".git"] = FileStat("link", 10, False)


def other_repository(con: sqlite3.Connection, slot: FakeWorktree, _repo: ScriptedPushRepo, _files: FakeSlotFiles) -> None:
    con.execute("INSERT INTO slot (repo_id,name,path) VALUES ('other','s1',?)", (str(slot.path),))
    con.execute("UPDATE attempt SET repo_id='other'")


def no_origin(_con: sqlite3.Connection, _slot: FakeWorktree, repo: ScriptedPushRepo, _files: FakeSlotFiles) -> None:
    repo.origin = False


def branch_missing(_con: sqlite3.Connection, slot: FakeWorktree, repo: ScriptedPushRepo, _files: FakeSlotFiles) -> None:
    repo.delete_branch("task/tl-1", expected=Sha(tip(slot.repo)))


def branch_rewritten(con: sqlite3.Connection, slot: FakeWorktree, _repo: ScriptedPushRepo, _files: FakeSlotFiles) -> None:
    slot.checkout_force("task/tl-1", str(con.execute("SELECT slot_head FROM attempt").fetchone()[0]))


@pytest.mark.parametrize(
    ("change", "reason", "opened"),
    [
        (abandoned, "abandoned", 0), (unverified, "not_verified", 0), (redirected, "repository", 0),
        (other_repository, "repository", 1), (no_origin, "no_remote", 2), (branch_missing, "branch_moved", 2),
        (branch_rewritten, "branch_moved", 2),
    ],
    ids=["abandoned", "not_verified", "redirected", "other_repository", "no_origin", "branch_missing", "branch_rewritten"],
)
def test_each_precondition_refuses_before_any_push(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, repo: ScriptedPushRepo, remote: FakeRemote, checkouts: Checkouts,
    slot_files: FakeSlotFiles, change: Callable[[sqlite3.Connection, FakeWorktree, ScriptedPushRepo, FakeSlotFiles], None], reason: str,
    opened: int,
) -> None:
    run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    change(registered, slot, repo, slot_files)
    pushes: list[bool] = []
    repo.during = lambda: pushes.append(True)
    git = Observed(checkouts)
    found = publisher(registered, git, slot_files).publish(KEY)
    assert isinstance(found, NotPublished) and (found.kind, found.reason, publish_word(found)) == ("refused", reason, f"refused:{reason}")
    assert (pushes, rows(registered), "task/tl-1" in remote.branches(), len(git.opened)) == ([], [], False, opened)


def test_absent_rejected_and_not_yet_verified_are_refused(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    git = Observed(checkouts)
    assert publisher(registered, git, slot_files).publish(AttemptKey("nope", "x", 1)) == NotPublished(
        "refused", "absent", "No such attempt. Nothing was pushed or recorded.")
    run(registered, tmp_path, slot, checkouts, slot_files, {P: " \n"}, release=False)  # rejected: plan_empty
    found = publisher(registered, git, slot_files).publish(KEY)
    assert isinstance(found, NotPublished) and found.reason == "not_verified" and "plan_empty" in found.detail and git.opened == []


def test_a_remote_ahead_that_contains_x_is_refused_and_never_recorded(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, repo: ScriptedPushRepo, remote: FakeRemote, checkouts: Checkouts,
    slot_files: SlotFiles,
) -> None:
    """`ls_remote` reads the fetch side, which a `pushurl` may make another repository: only `Pushed` is recorded."""
    x = run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    repo.worktree(repo.path).push("task/tl-1", head=Sha(x))  # someone published X, then added a commit on top
    t = remote.advance("task/tl-1", {"later.md": "more"})
    repo.fetch("origin")
    found = publisher(registered, checkouts, slot_files).publish(KEY)
    assert isinstance(found, NotPublished) and (found.kind, found.reason) == ("refused", "remote_ahead") and t in found.detail
    assert rows(registered) == [] and remote.branches()["task/tl-1"] == t


def test_a_rejected_push_records_nothing_even_when_the_remote_tip_is_x_and_a_rerun_records(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, repo: ScriptedPushRepo, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    x = run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    repo.worktree(repo.path).push("task/tl-1", head=Sha(x))  # another publisher won the race
    repo.answer = RefRejected("! [rejected] (fetch first)")
    found = publisher(registered, checkouts, slot_files).publish(KEY)
    assert isinstance(found, NotPublished) and (found.kind, found.reason) == ("unavailable", "changed") and rows(registered) == []
    repo.answer = None
    assert publisher(registered, checkouts, slot_files).publish(KEY) == BranchPublished(x, x)  # Pushed: up to date


def d_on_origin(con: sqlite3.Connection, repo: ScriptedPushRepo, _remote: FakeRemote) -> str:
    """origin's task/tl-1 at D, behind X: a push that raced with this one."""
    d = str(con.execute("SELECT slot_head FROM attempt").fetchone()[0])
    repo.worktree(repo.path).push("task/tl-1", head=Sha(d))
    return d


def offline_after(_con: sqlite3.Connection, _repo: ScriptedPushRepo, remote: FakeRemote) -> str:
    remote.offline = True  # the push is scripted; the `ls_remote` after it cannot reach origin
    return ""


def unreadable(_con: sqlite3.Connection, repo: ScriptedPushRepo, remote: FakeRemote) -> str:
    t = remote.advance("task/tl-1", {"other.md": "unrelated"})
    repo.fetch("origin")
    repo.unreadable = (t, GitTimeout("git timed out"))
    return t


@pytest.mark.parametrize(
    ("arrange", "expected"),
    [
        (lambda _c, _r, _m: "", ("unavailable", "changed")),  # the tip was deleted meanwhile
        (d_on_origin, ("unavailable", "changed")),
        (offline_after, ("unavailable", "remote")),
        (unreadable, ("unavailable", "git")),
    ],
    ids=["tip_absent", "tip_behind_x", "ls_remote_fails", "ancestry_timeout"],
)
def test_a_rejected_push_that_is_not_a_refusal_is_rerun_able_and_records_nothing(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, repo: ScriptedPushRepo, remote: FakeRemote, checkouts: Checkouts,
    slot_files: SlotFiles, arrange: Callable[[sqlite3.Connection, ScriptedPushRepo, FakeRemote], str], expected: tuple[str, str],
) -> None:
    run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    before = arrange(registered, repo, remote)
    repo.answer = RefRejected("! [rejected] (non-fast-forward)")
    found = publisher(registered, checkouts, slot_files).publish(KEY)
    assert isinstance(found, NotPublished) and (found.kind, found.reason) == expected and rows(registered) == []
    assert remote.branches().get("task/tl-1", "") == before


def test_a_diverged_remote_is_refused_and_kept_and_an_unknown_tip_is_remote_moved(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, repo: ScriptedPushRepo, remote: FakeRemote, checkouts: Checkouts,
    slot_files: SlotFiles,
) -> None:
    run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    t = remote.advance("task/tl-1", {"other.md": "unrelated"})  # another branch of the same name, unknown here
    moved = publisher(registered, checkouts, slot_files).publish(KEY)
    assert isinstance(moved, NotPublished) and (moved.kind, moved.reason) == ("refused", "remote_moved") and t in moved.detail
    repo.fetch("origin")
    diverged = publisher(registered, checkouts, slot_files).publish(KEY)
    assert isinstance(diverged, NotPublished) and (diverged.kind, diverged.reason) == ("refused", "diverged") and t in diverged.detail
    assert remote.branches()["task/tl-1"] == t and rows(registered) == []  # never forced


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (None, ("unavailable", "remote")),
        (RemoteRejected("! [remote rejected] protected branch"), ("refused", "remote_rejected")),
        (Rejected("! [rejected] protected by policy"), ("refused", "remote_rejected")),
        (HookRejected("pre-push hook declined: protected"), ("unavailable", "git")),
        (GitUnavailable("git exited 128"), ("unavailable", "git")),
    ],
    ids=["offline", "remote_rejected", "plain_rejected", "hook_rejected", "git_unavailable"],
)
def test_a_push_that_does_not_land_records_nothing_and_prints_no_git_output(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, repo: ScriptedPushRepo, remote: FakeRemote, checkouts: Checkouts,
    slot_files: SlotFiles, answer: PushResult | GitUnavailable | None, expected: tuple[str, str],
) -> None:
    run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    remote.offline = answer is None
    repo.answer = answer
    found = publisher(registered, checkouts, slot_files).publish(KEY)
    assert isinstance(found, NotPublished) and (found.kind, found.reason) == expected and rows(registered) == []
    assert all(text not in found.detail for text in ("protected", "128", "Could not resolve host"))  # no Git output carried


def test_an_abandon_committed_during_the_push_is_refused_and_records_nothing(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, repo: ScriptedPushRepo, remote: FakeRemote, checkouts: Checkouts,
    slot_files: FakeSlotFiles,
) -> None:
    x = run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    repo.during = lambda: abandoned(registered, slot, repo, slot_files)
    found = publisher(registered, checkouts, slot_files).publish(KEY)
    assert isinstance(found, NotPublished) and (found.kind, found.reason) == ("refused", "abandoned")
    assert rows(registered) == [] and remote.branches()["task/tl-1"] == x  # the remote keeps X; nothing else is undone


def test_a_failed_record_is_unavailable_store_and_a_rerun_records_it(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    x = run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})

    def refused(_con: sqlite3.Connection) -> AbstractContextManager[None]:
        raise sqlite3.OperationalError("database is locked")

    failing = publisher(registered, checkouts, slot_files, AttemptStore(lambda: registered, refused))
    found = failing.publish(KEY)
    assert isinstance(found, NotPublished) and (found.kind, found.reason) == ("unavailable", "store") and rows(registered) == []
    assert publisher(registered, checkouts, slot_files).publish(KEY) == BranchPublished(x, x)  # pushed again: up to date


def test_two_publishers_at_once_record_one_row(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, repo: ScriptedPushRepo, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    x = run(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"})
    inner: list[PublishResult] = []
    started: list[bool] = []

    def other() -> None:
        if not started:  # once: the other publisher's own push runs this hook too
            started.append(True)
            inner.append(publisher(registered, checkouts, slot_files).publish(KEY))

    repo.during = other
    outer = publisher(registered, checkouts, slot_files).publish(KEY)
    assert inner == [BranchPublished(x, x)] and outer == PublishedRow(x, x, 40.0) and len(rows(registered)) == 1
