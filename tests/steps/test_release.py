"""Release (settled) and abandon over the in-memory factory.db, the semantic Git fake, the fake slot file port, scripted
entry and agent observations, a recording tracker unclaim, the real slot lock and a fake clock: what each call changes,
every refusal with nothing changed, and the fences every other writer meets afterwards."""

import json
import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import NoReturn, Protocol

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from beads_client import BdError
from git_porcelain import Repo, WorktreeInfo
from git_porcelain.testing import FakeWorktree
from sqlite_store import begin_immediate

from taskloop.admit import AdmitRefused, AttemptAdmission, RepeatRequest
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore, StoreRefused
from taskloop.attempt_types import AttemptKey, Checkouts, FileEntry, Seen, SlotFiles, Verified
from taskloop.evidence_files import EvidenceFiles
from taskloop.repo import RepoId
from taskloop.slot_lock import custody, lock_path, probe
from taskloop.slot_release import AlreadyReleased, NotReleased, Released, SlotRelease, word
from taskloop.slots import adopt, observe
from taskloop.verifier import Verifier

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "Plan written"}


def head(slot: FakeWorktree) -> str:
    found = next(worktree.head for worktree in slot.repo.worktrees() if worktree.path == slot.path)
    assert found is not None
    return found


def tip(slot: FakeWorktree) -> str:
    return next(entry.sha for entry in slot.repo.refs(["refs/heads/task"]) if entry.name == "refs/heads/task/tl-1")


def never(*_args: object) -> NoReturn:
    raise AssertionError("not reached")


class Ports:
    """A release's collaborators: Git opens and lock takes counted, the entry and the agent observed as scripted, the
    tracker's unclaim answered from a script (True, False or a BdError) and recorded."""

    def __init__(self, con: sqlite3.Connection, checkouts: Checkouts, files: SlotFiles, seen: Seen = "gone", alive: bool = False) -> None:
        self.con, self.git, self.files, self.seen, self.alive = con, checkouts, files, seen, alive
        self.opens, self.holds, self.observed = 0, 0, list[tuple[int, str, str]]()
        self.answers: list[bool | BdError] = [True]
        self.unclaimed: list[tuple[str, str]] = []
        self.inside: Callable[[], object] = lambda: None

    def checkouts(self, path: Path) -> Repo:
        self.opens += 1
        return self.git(path)

    def observe(self, entry: tuple[int, str, str]) -> Seen:
        self.observed.append(entry)
        return self.seen

    def gone(self, _worker: Worker) -> bool:
        return not self.alive

    @contextmanager
    def hold(self, cwd: str, attempt_id: str) -> Generator[None]:
        self.holds += 1
        with custody(cwd, attempt_id):
            self.inside()
            yield

    def unclaim(self, tracker_root: str, task_id: str) -> bool:
        self.unclaimed.append((tracker_root, task_id))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BdError):
            raise answer
        return answer

    def releaser(self) -> SlotRelease:
        return SlotRelease(AttemptStore(lambda: self.con), self.checkouts, self.files, self.observe, self.gone, self.hold, self.unclaim,
                           lambda: 30)


def agent(slot: FakeWorktree, files: dict[str, str], rc: int = 0) -> Callable[[Harness, LaunchSpec, float, RunHooks | None], RunOutcome]:
    def call(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        for path, text in files.items():
            slot.write_file(path, text)
        outcome = RunOutcome(rc=rc, worker=WORKER, summary=Summary(text=json.dumps(PLAN), rc=rc, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    return call


def executed(con: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, files: SlotFiles,
             written: dict[str, str], rc: int = 0) -> str:
    """The registered attempt run once (the slot prepared on `task/tl-1`): its result's reason."""
    store = AttemptStore(lambda: con)
    attempts = Attempts(store, EvidenceFiles(tmp_path), lambda: ("/bin/codex", {}), agent(slot, written, rc), lambda: 10, checkouts, files)
    return attempts.execute(KEY, ENTRY).reason


def verified(con: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, files: SlotFiles) -> str:
    """The registered attempt run and verified: X, on `task/tl-1`."""
    assert executed(con, tmp_path, slot, checkouts, files, {P: "# Plan\n"}) == "verification"
    store = AttemptStore(lambda: con)
    assert isinstance(Verifier(store, checkouts, files, lambda _w: True, lambda: 20, nowhere).verify(KEY), Verified)
    return head(slot)


@contextmanager
def nothing() -> Generator[None]:
    yield


def nowhere(_admission: object) -> AbstractContextManager[None]:
    return nothing()


def stored(con: sqlite3.Connection) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    """The reservations and the release rows."""
    return (con.execute("SELECT slot,generation,attempt_id FROM reservation").fetchall(),
            con.execute("SELECT head,released_at,abandoned,claim FROM plan_release").fetchall())


def test_a_settled_release_parks_the_verified_slot_at_d_keeps_the_claim_and_then_has_nothing_pending(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    d = head(slot)
    x = verified(registered, tmp_path, slot, checkouts, slot_files)
    ports = Ports(registered, checkouts, slot_files)
    assert ports.releaser().release(KEY, False) == Released("s1", d, True, "kept", False)
    assert (slot.branch(), head(slot), tip(slot)) == (None, d, x)  # detached at D; the branch keeps X
    assert stored(registered) == ([], [(d, 30.0, 0, "kept")]) and ports.unclaimed == [] and ports.holds == 1
    ports.opens = ports.holds = 0
    again = ports.releaser().release(KEY, False)
    assert again == AlreadyReleased("s1", "kept", False) and word(again) == "released" and (ports.opens, ports.holds) == (0, 0)


@pytest.mark.parametrize("phase", ["admitted", "registered", "captured"])
def test_settled_before_the_step_ended_is_not_terminal_and_changes_nothing(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles, phase: str
) -> None:
    if phase == "registered":
        registered.execute("UPDATE plan_attempt SET phase='registered',base_commit=?,worker_pid=42,worker_pgid=42,worker_start='s',"
                           "worker_boot='b'", (head(slot),))
    elif phase == "captured":  # pending verification
        assert executed(registered, tmp_path, slot, checkouts, slot_files, {P: "# Plan\n"}) == "verification"
    before, ports = stored(registered), Ports(registered, checkouts, slot_files)
    found = ports.releaser().release(KEY, False)
    assert isinstance(found, NotReleased) and (found.kind, found.reason) == ("refused", "not_terminal")
    assert (stored(registered), ports.opens, ports.holds, ports.observed) == (before, 0, 0, [])


WORKING = "UPDATE plan_attempt SET phase=?,base_commit='" + "b" * 40 + "',worker_pid=?,worker_pgid=?,worker_start=?,worker_boot=?"


@pytest.mark.parametrize(
    ("seen", "alive", "phase", "worker", "expected"),
    [
        ("matching", False, "admitted", None, ("refused", "entry_running")),
        ("unknown", False, "admitted", None, ("unavailable", "observe")),
        ("gone", True, "registered", WORKER, ("unsettled", "worker_alive")),
        ("different_process", True, "captured", WORKER, ("unsettled", "worker_alive")),
        ("gone", False, "dispatching", None, ("unsettled", "worker_unknown")),
    ],
    ids=["entry_running", "entry_unknown", "agent_alive", "group_alive", "dispatching_without_agent"],
)
def test_abandon_without_a_stop_proof_takes_no_lock_and_reads_no_git(
    registered: sqlite3.Connection, checkouts: Checkouts, slot_files: SlotFiles,
    seen: Seen, alive: bool, phase: str, worker: Worker | None, expected: tuple[str, str],
) -> None:
    if phase != "admitted":
        identity = (None,) * 4 if worker is None else (worker.pid, worker.pgid, worker.start, worker.boot)
        registered.execute(WORKING, (phase, *identity))
    before, ports = stored(registered), Ports(registered, checkouts, slot_files, seen, alive)
    found = ports.releaser().release(KEY, True)
    assert isinstance(found, NotReleased) and (found.kind, found.reason) == expected
    assert found.detail.endswith("Nothing changed.") and (found.reason != "entry_running" or "pid 7" in found.detail)
    assert (stored(registered), ports.opens, ports.holds, ports.unclaimed) == (before, 0, 0, [])


def test_the_entry_releasing_itself_passes_its_own_identity(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    verified(registered, tmp_path, slot, checkouts, slot_files)
    ports = Ports(registered, checkouts, slot_files, seen="matching")
    assert isinstance(ports.releaser().release(KEY, False, ENTRY), Released) and ports.observed == []


def test_abandon_an_admitted_attempt_on_a_detached_slot_needs_no_git_write(
    admitted: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """Never registered, never prepared: nothing to park; the reservation goes, the claim returns at the stored root."""
    con = sqlite3.connect(admitted, isolation_level=None)
    d, ports = head(slot), Ports(con, checkouts, slot_files)
    assert ports.releaser().release(KEY, True) == Released("s1", None, True, "unclaimed", True)
    assert stored(con) == ([], [(d, 30.0, 1, "unclaimed")]) and ports.unclaimed == [("/tracker", "tl-1")] and slot.branch() is None
    con.close()


def test_abandon_a_prepared_admitted_attempt_parks_it_at_d(
    registered: sqlite3.Connection, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    d = head(slot)
    slot.take_branch("task/tl-1", "HEAD", mode="resume")
    ports = Ports(registered, checkouts, slot_files)
    assert ports.releaser().release(KEY, True) == Released("s1", d, True, "unclaimed", True)
    assert (slot.branch(), head(slot), tip(slot)) == (None, d, d) and ports.unclaimed == [("/tracker", "tl-1")]


class FakeFiles(SlotFiles, Protocol):
    """The conftest's fake slot file port, as these tests use it: `entries` overrides any path."""

    entries: dict[Path, FileEntry | None]


def unborn(slot: FakeWorktree, _files: FakeFiles, monkeypatch: pytest.MonkeyPatch) -> None:
    info = WorktreeInfo(slot.path, None, "task/tl-1", False, None)
    monkeypatch.setattr(slot.repo, "worktrees", lambda *, with_dirty=False: (info,))


def redirected(slot: FakeWorktree, files: FakeFiles, _monkeypatch: pytest.MonkeyPatch) -> None:
    files.entries[slot.path / ".git"] = FileEntry("link", 10, False)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda slot, _f, _m: slot.write_file("docs/design/tl-1/x.md", "x"), "slot_dirty"),
        (lambda slot, _f, _m: (slot.write_file("README", "two"), slot.stage(["README"])), "slot_dirty"),
        (lambda slot, _f, _m: slot.checkout_new("other"), "slot_branch"),
        (redirected, "slot_redirected"),
        (unborn, "slot_unborn"),
    ],
    ids=["dirty", "staged", "other_branch", "redirected", "unborn"],
)
def test_a_slot_that_is_not_clean_on_its_branch_is_refused_and_stays_held(
    registered: sqlite3.Connection, slot: FakeWorktree, checkouts: Checkouts, slot_files: FakeFiles, monkeypatch: pytest.MonkeyPatch,
    change: Callable[[FakeWorktree, FakeFiles, pytest.MonkeyPatch], object], reason: str,
) -> None:
    slot.take_branch("task/tl-1", "HEAD", mode="resume")
    change(slot, slot_files, monkeypatch)
    before, ports = stored(registered), Ports(registered, checkouts, slot_files)
    found = ports.releaser().release(KEY, True)
    assert isinstance(found, NotReleased) and (found.kind, found.reason, word(found)) == ("refused", reason, f"held:{reason}")
    assert (stored(registered), ports.unclaimed, ports.holds) == (before, [], 1)
    assert reason != "slot_redirected" or ports.opens == 0  # the pointer is read first: no Git call
    assert reason != "slot_dirty" or ("x.md" in found.detail or "README" in found.detail)


def test_a_held_slot_lock_is_slot_busy(
    registered: sqlite3.Connection, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles,
    occupy: Callable[[Path], AbstractContextManager[None]],
) -> None:
    before, ports = stored(registered), Ports(registered, checkouts, slot_files)
    with occupy(lock_path(str(slot.path))):
        found = ports.releaser().release(KEY, True)
    assert found == NotReleased("unavailable", "slot_busy", "Another entry, verify or release holds the slot. Nothing changed.")
    assert (stored(registered), ports.opens, ports.unclaimed) == (before, 0, [])


def test_an_attempt_changed_after_the_proof_records_nothing_and_says_it_parked(
    registered: sqlite3.Connection, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """A relaunch registers another entry while the release holds the lock: the fence on `rev` refuses the transaction."""
    d = head(slot)
    slot.take_branch("task/tl-1", "HEAD", mode="resume")
    before, ports = stored(registered), Ports(registered, checkouts, slot_files)
    ports.inside = lambda: registered.execute("UPDATE plan_attempt SET entry_pid=8,rev=rev+1")
    found = ports.releaser().release(KEY, True)
    assert isinstance(found, NotReleased) and (found.kind, found.reason) == ("unavailable", "changed")
    assert f"parked at {d}" in found.detail and stored(registered) == before and ports.unclaimed == []


def test_the_claim_is_returned_once_retried_while_bd_fails_and_reported_when_not_ours(
    registered: sqlite3.Connection, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    d, ports = head(slot), Ports(registered, checkouts, slot_files)
    ports.answers = [BdError("other", "down"), True]
    failed = ports.releaser().release(KEY, True)
    assert isinstance(failed, NotReleased) and (failed.kind, failed.reason) == ("unavailable", "tracker")
    assert stored(registered) == ([], [(d, 30.0, 1, "unclaiming")])  # released; the claim still to return
    assert ports.releaser().release(KEY, True) == Released("s1", None, False, "unclaimed", True)
    assert ports.releaser().release(KEY, True) == AlreadyReleased("s1", "unclaimed", True)
    assert ports.unclaimed == [("/tracker", "tl-1")] * 2 and stored(registered)[1] == [(d, 30.0, 1, "unclaimed")]
    other = Ports(registered, checkouts, slot_files)
    registered.execute("UPDATE plan_release SET abandoned=0,claim='kept'")  # as if settled, to abandon again
    other.answers = [False]
    assert other.releaser().release(KEY, True) == Released("s1", None, False, "not_held", True)


def test_abandoning_a_settled_release_flips_it_and_returns_the_claim_with_no_git(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    d = head(slot)
    verified(registered, tmp_path, slot, checkouts, slot_files)
    assert isinstance(Ports(registered, checkouts, slot_files).releaser().release(KEY, False), Released)
    ports = Ports(registered, checkouts, slot_files)
    assert ports.releaser().release(KEY, True) == Released("s1", None, False, "unclaimed", True)
    assert (ports.opens, ports.holds, ports.unclaimed) == (0, 0, [("/tracker", "tl-1")])
    assert stored(registered) == ([], [(d, 30.0, 1, "unclaimed")])


def test_after_a_release_every_other_writer_meets_the_fence_and_the_slot_is_free_again(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles, root: Path,
    occupy: Callable[[Path], AbstractContextManager[None]],
) -> None:
    verified(registered, tmp_path, slot, checkouts, slot_files)
    assert isinstance(Ports(registered, checkouts, slot_files).releaser().release(KEY, False), Released)
    store = AttemptStore(lambda: registered)
    with pytest.raises(StoreRefused, match="stale_reservation"):
        store.load(KEY)
    assert store.register_entry(KEY, (8, "later", "boot"), 10) == "refused"
    admission = AttemptAdmission(
        lambda: registered, begin_immediate, EvidenceFiles(tmp_path), never, never, never, never, lambda: 10, never
    )
    assert admission.admit_repeat(RepeatRequest(KEY, "feedback", 1000, "unsafe")) == AdmitRefused("not_repeatable")
    opened: list[Path] = []

    def counted(path: Path) -> Repo:
        opened.append(path)
        return checkouts(path)

    assert isinstance(Verifier(store, counted, slot_files, never, lambda: 20, never).verify(KEY), Verified) and opened == []
    adopt(lambda: registered, begin_immediate, slot.repo, root, 1)  # the freed slot, detached and clean, is free again
    repo_id = RepoId(slot.repo.identity().key)
    assert [view.state for view in observe(registered, slot.repo, repo_id, probe)] == ["free"]
    with occupy(lock_path(str(slot.path))):  # a release still parking it holds the lock: never free
        assert [(view.state, view.reason) for view in observe(registered, slot.repo, repo_id, probe)] == [("unknown", "locked")]


def test_a_clean_detached_slot_moved_off_d_is_parked_back_at_d(
    registered: sqlite3.Connection, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """A person moved the reserved slot to another commit, detached and clean: the next admission takes its HEAD as D, so
    the release returns it to D."""
    d = head(slot)
    slot.checkout_new("elsewhere")
    slot.write_file("README", "two")
    slot.stage(["README"])
    slot.record("moved", paths="all")
    slot.park(head(slot))
    assert head(slot) != d and slot.branch() is None
    assert Ports(registered, checkouts, slot_files).releaser().release(KEY, True) == Released("s1", d, True, "unclaimed", True)
    assert (head(slot), slot.branch()) == (d, None)
