"""The checks release (S6c, tl-8bh9.14.6 section 10) over a factory.db file (the `on_slot` checks attempt), the semantic Git
fake's slot, scripted entry and command observations and the real slot lock: the reset to X before the park, the stop
proof in both modes, the refusals that change nothing, the abandon of a released checks attempt, and the task's abandon
order against the implement attempt's `SlotRelease`."""

import dataclasses
import sqlite3
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest
from doubles import CHECKS, REQUIRED, FakeSlotFiles, PinnedViews
from git_porcelain.testing import FakeWorktree
from sqlite_store import Store
from stream_proc import OwnedProcess

from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, EntryIdentity, Seen
from taskloop.check_release import ChecksRelease
from taskloop.check_store import ChecksAdmitted, CheckStore, insert
from taskloop.factory_schema import SCHEMA
from taskloop.setup_store import ProcessSeen, SetupStore
from taskloop.slot_lock import custody, lock_path
from taskloop.slot_release import AlreadyReleased, NotReleased, Released, ReleaseResult, SlotRelease, release_word

ENTRY = (7, "entry-start", "boot")
IMPLEMENT = AttemptKey("implement", "implement-token", 1)
COMMAND = OwnedProcess(600, 600, "command-start", "boot")
SETUP = OwnedProcess(700, 700, "setup-start", "boot")


@dataclasses.dataclass
class Bench:
    """One checks attempt's releases: `entry` answers for its registered entry, `seen` for a command by pid (default
    gone); `inside` runs under the lock; `emptied` lists each scratch emptied, `unclaimed` each claim returned."""

    con: sqlite3.Connection
    slot: FakeWorktree
    views: PinnedViews
    files: FakeSlotFiles
    entry: Seen = "gone"
    seen: dict[int, ProcessSeen] = dataclasses.field(default_factory=dict)
    inside: Callable[[], object] = lambda: None
    emptied: list[Path] = dataclasses.field(default_factory=list)
    unclaimed: list[str] = dataclasses.field(default_factory=list)
    holds: int = 0

    def __post_init__(self) -> None:
        self.store = CheckStore(lambda: self.con)
        self.d = self.head()
        self.x = self.con.execute("SELECT end_commit FROM attempt WHERE attempt_id='implement'").fetchone()[0]

    def head(self) -> str:
        found = next(info.head for info in self.slot.repo.worktrees() if info.path == self.slot.path)
        assert found is not None
        return found

    def setup_seen(self, process: OwnedProcess) -> ProcessSeen:
        return self.seen.get(process.pid, "gone")

    def observe(self, _entry: EntryIdentity) -> Seen:
        return self.entry

    @contextmanager
    def hold(self, slot_path: str, attempt_id: str) -> Generator[None]:
        self.holds += 1
        with custody(slot_path, attempt_id):
            self.inside()
            yield

    def scratch(self, path: Path) -> bool:
        self.emptied.append(path)
        return True

    def release(self, abandon: bool = False, me: EntryIdentity | None = None, key: AttemptKey = CHECKS) -> ReleaseResult:
        released = ChecksRelease(self.store, self.views, self.files, self.observe, self.hold, lambda: 30, self.setup_seen, self.scratch)
        return released.release(key, abandon, me)

    def implement(self) -> ReleaseResult:
        """The task's abandon, second half: the implement attempt's own `SlotRelease` (its release row is `kept`)."""
        def unclaim(_root: str, task_id: str) -> bool:
            self.unclaimed.append(task_id)
            return True

        def nowhere(_path: str, _attempt: str) -> AbstractContextManager[None]:
            raise AssertionError("an implement attempt released before needs no lock")

        released = SlotRelease(AttemptStore(lambda: self.con), self.views, self.files, self.observe, lambda _w: True, nowhere, unclaim,
                               lambda: 40, self.setup_seen, self.scratch)
        return released.release(IMPLEMENT, True)

    def at_x(self) -> None:
        self.slot.park(self.x)

    def concluded(self) -> None:
        self.store.conclude(CHECKS, "passed", None, 20)

    def stored(self) -> tuple[object, ...]:
        """The reservations, then the checks attempt's release columns."""
        held = self.con.execute("SELECT slot,attempt_id FROM reservation").fetchall()
        return held, self.con.execute("SELECT released_at,parked,abandoned FROM checks_attempt WHERE attempt_id='checks'").fetchone()


@pytest.fixture
def bench(on_slot: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: FakeSlotFiles) -> Generator[Bench]:
    con = Store(SCHEMA).open_rw(on_slot)
    assert con is not None
    yield Bench(con, slot, checkouts, slot_files)
    con.close()


UNRELEASED = ([("s1", "checks")], (None, None, 0))


def test_a_concluded_attempt_is_reset_to_exactly_x_then_parked_at_d_and_freed(bench: Bench) -> None:
    """The untracked leftovers of a passed block (and an ignored folder, a rewritten tracked file) would refuse the park."""
    bench.at_x()
    bench.slot.repo.exclude_locally([".venv/"])
    bench.slot.write_file("coverage.xml", "left by a check")
    bench.slot.write_file(".venv/planted", "ignored")
    bench.slot.write_file("README", "rewritten")
    bench.concluded()
    assert bench.release() == Released("s1", bench.d, True, "kept", False)
    assert (bench.head(), bench.slot.branch()) == (bench.d, None)
    assert [bench.slot.read_file(path) for path in ("coverage.xml", ".venv/planted", "README")] == [None, None, "one"]
    assert bench.stored() == ([], (30.0, bench.d, 0)) and bench.emptied == [bench.slot.path] and bench.holds == 1
    again = bench.release()
    assert again == AlreadyReleased("s1", "kept", False) and release_word(again) == "already_released" and bench.holds == 1


def test_a_slot_still_detached_at_d_is_released_with_no_git_write(bench: Bench) -> None:
    bench.concluded()
    assert bench.release() == Released("s1", None, True, "kept", False)
    assert bench.stored() == ([], (30.0, bench.d, 0)) and bench.head() == bench.d


def test_settled_refuses_an_attempt_that_has_not_concluded(bench: Bench) -> None:
    bench.at_x()
    bench.slot.write_file("left", "untracked")
    found = bench.release()
    assert isinstance(found, NotReleased) and found.word == "refused:not_terminal"
    assert bench.stored() == UNRELEASED and bench.slot.read_file("left") == "untracked" and bench.holds == 0


def running_check(bench: Bench, conclusion: str | None = None, process: OwnedProcess | None = COMMAND) -> None:
    """Block 1's check `check` started, its command registered (unless None), concluded as given."""
    bench.store.start(CHECKS, bench.store.block(CHECKS), 0, "check", REQUIRED[0][1], 600, 10)
    if process is not None:
        bench.store.registered(CHECKS, 1, 0, process)
    if conclusion is not None:
        bench.con.execute("UPDATE check_result SET conclusion=?,ended_at=11", (conclusion,))


def running_setup(bench: Bench) -> None:
    setups = SetupStore(lambda: bench.con)
    setups.start(CHECKS, 1, bench.x, "e" * 64, 10)
    setups.registered(CHECKS, 1, 0, SETUP)


@pytest.mark.parametrize("abandon", [False, True], ids=["settled", "abandon"])
@pytest.mark.parametrize(("arrange", "word"), [
    (lambda b: (b.store.register_entry(CHECKS, ENTRY, 10), setattr(b, "entry", "matching")), "refused:entry_running"),
    (lambda b: (b.store.register_entry(CHECKS, ENTRY, 10), setattr(b, "entry", "unknown")), "unavailable:observe"),
    (lambda b: (running_setup(b), b.seen.update({700: "alive"})), "held:setup_running"),
    (lambda b: (running_setup(b), b.seen.update({700: "unknown"})), "unavailable:setup_unknown"),
    (lambda b: (running_check(b), b.seen.update({600: "alive"})), "held:check_running"),
    (lambda b: (running_check(b, "lingering"), b.seen.update({600: "alive"})), "held:check_running"),
    (lambda b: (running_check(b, "timed_out"), b.seen.update({600: "unknown"})), "unavailable:check_unknown"),
], ids=["entry_running", "entry_unknown", "setup_running", "setup_unknown", "check_running", "lingering_alive", "check_unknown"])
def test_the_stop_proof_holds_the_slot_in_both_modes_and_changes_nothing(
    bench: Bench, arrange: Callable[[Bench], object], word: str, abandon: bool
) -> None:
    bench.at_x()
    bench.slot.write_file("left", "untracked")
    arrange(bench)
    bench.concluded()
    assert release_word(bench.release(abandon)) == word
    assert bench.stored() == UNRELEASED and bench.holds == 0 and bench.slot.read_file("left") == "untracked"


@pytest.mark.parametrize("arrange", [
    lambda b: (b.store.register_entry(CHECKS, ENTRY, 10), setattr(b, "entry", "matching")),
    lambda b: running_check(b, "passed"),
    lambda b: running_check(b, None, None),
    lambda b: running_check(b, "interrupted"),
    running_setup,
], ids=["me", "settled_result", "never_registered", "gone_interrupted", "setup_gone"])
def test_the_entry_itself_a_settled_or_gone_command_passes_the_proof(bench: Bench, arrange: Callable[[Bench], object]) -> None:
    arrange(bench)
    bench.concluded()
    assert release_word(bench.release(me=ENTRY)) == "released"


def test_a_slot_not_detached_at_x_is_never_reset_and_the_park_refuses(bench: Bench) -> None:
    bench.at_x()
    bench.slot.checkout_new("elsewhere")
    bench.slot.write_file("README", "work")
    bench.concluded()
    assert release_word(bench.release()) == "held:slot_dirty"
    assert (bench.slot.branch(), bench.slot.read_file("README")) == ("elsewhere", "work") and bench.stored() == UNRELEASED
    bench.slot.write_file("README", "X")
    assert release_word(bench.release()) == "held:slot_branch"  # a branch is never parked away from a checks slot


def test_a_busy_lock_and_a_changed_attempt_refuse_and_record_nothing(bench: Bench) -> None:
    bench.concluded()
    with custody(str(bench.slot.path), "someone"):
        assert release_word(bench.release()) == "unavailable:slot_busy"
    assert bench.stored() == UNRELEASED and lock_path(str(bench.slot.path)).exists()
    bench.inside = lambda: bench.con.execute("UPDATE checks_attempt SET rev=rev+1")  # another writer after the proof
    found = bench.release()
    assert isinstance(found, NotReleased) and found.word == "unavailable:changed" and bench.stored() == UNRELEASED


def test_an_unknown_key_is_absent_and_a_closed_store_unavailable(bench: Bench) -> None:
    assert release_word(bench.release(key=AttemptKey("checks", "other", 1))) == "refused:absent"
    bench.con.close()
    assert release_word(bench.release()) == "unavailable:store"


def test_an_abandon_of_an_admitted_attempt_releases_it_and_then_the_implement_abandon_returns_the_claim(bench: Bench) -> None:
    """The task's abandon, checks first: the implement attempt's abandon refuses `changed` until then (`SUCCESSOR`)."""
    bench.at_x()
    bench.slot.write_file("coverage.xml", "left")
    first = bench.implement()
    assert isinstance(first, NotReleased) and first.word == "refused:changed" and bench.unclaimed == []
    assert bench.release(abandon=True) == Released("s1", bench.d, True, "kept", True)
    assert bench.stored() == ([], (30.0, bench.d, 1)) and bench.slot.read_file("coverage.xml") is None
    assert bench.implement() == Released("s0", None, False, "unclaimed", True) and bench.unclaimed == ["tl-1"]
    assert bench.release(abandon=True) == AlreadyReleased("s1", "kept", True)  # the rerun of the first half


def test_the_other_race_order_a_checks_row_after_the_implement_flip_is_still_released_then_the_claim_returned(bench: Bench) -> None:
    """The implement abandon's flip committed first (`unclaiming`), the checks admission's row written anyway: the
    abandon's rerun releases the checks attempt, then finishes the implement attempt's unclaim."""
    bench.con.execute("UPDATE slot_release SET claim='unclaiming' WHERE attempt_id='implement'")
    assert bench.release(abandon=True) == Released("s1", None, True, "kept", True)
    assert bench.implement() == Released("s0", None, False, "unclaimed", True)


def test_an_abandon_of_a_released_attempt_only_flips_it_once_and_only_the_latest(bench: Bench) -> None:
    bench.concluded()
    assert release_word(bench.release()) == "released"
    holds = bench.holds
    assert bench.release(abandon=True) == Released("s1", None, False, "kept", True)
    assert bench.release(abandon=True) == AlreadyReleased("s1", "kept", True) and bench.holds == holds
    assert bench.stored() == ([], (30.0, bench.d, 1))


def test_an_abandon_of_a_released_attempt_that_is_not_the_latest_changes_nothing(bench: Bench) -> None:
    bench.concluded()
    assert release_word(bench.release()) == "released"
    rerun = AttemptKey("rerun", "rerun-token", 1)
    bench.con.execute("INSERT INTO reservation VALUES ('s1',?,1,'rerun')", (bench.slot.repo.identity().key,))
    insert(bench.con, ChecksAdmitted(rerun, "implement", 2, "s1", bench.d, bench.x, REQUIRED, 100.0))
    found = bench.release(abandon=True)
    assert isinstance(found, NotReleased) and found.word == "unavailable:changed"
    assert bench.stored() == ([("s1", "rerun")], (30.0, bench.d, 0))

