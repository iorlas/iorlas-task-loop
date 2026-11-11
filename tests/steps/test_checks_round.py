"""The round takes a task through its check step (S6e, tl-8bh9.14.6 section 9), end to end over a factory.db file, the
rounds bench (`round_bench`: real admission, verify, release and publish, scripted agents, the Git fake), the real checks
admission at a `main` requiring `check` and `test`, and the real checks launcher (`launch.Launcher` over `CheckStore`)
whose registered start runs a scripted checks entry at once: it registers, then concludes and releases its slot as the
entry does, counts a relaunchable refusal, stays running, crashes before counting, or never starts."""

import json
import sqlite3
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from doubles import MAIN_PROFILE, PinnedViews
from git_porcelain import Recorded
from git_porcelain.testing import FakeWorktree
from round_bench import Factory, Tracker, scripts, task
from sqlite_store import Store, begin_immediate
from stream_proc import OwnedProcess, ProcessObservation

from taskloop.attempt_types import AttemptKey, EntryIdentity, Seen, SlotFiles
from taskloop.check_admit import ChecksAdmission
from taskloop.check_release import ChecksRelease
from taskloop.check_store import CheckStore
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitProfileFiles
from taskloop.launch import CHECK_ENTRY_MODULE, Launcher, LaunchResult
from taskloop.operations import LATE, ChecksPorts, Started, StartPorts, StartRequest, start
from taskloop.slot_lock import custody
from taskloop.slot_release import Released

AFTER_DEADLINE = 31 * 60  # past a checks attempt's deadline: the rounds' --minutes is 30


@dataclass(frozen=True)
class Pipes:
    stdin: None = None
    stdout: None = None


class Checking(Factory):
    """The rounds bench with the check step: `bodies` is what each started checks entry does, in order: `passed`,
    `failed` (`test:failed`), `expired`, `counted` (a relaunchable refusal the entry counts), `crash` (ends before counting:
    a crash, or a refusal before the attempt is its own), `running` (until `finish`), `unstartable` (the start fails,
    nothing registered). `entries`: each started entry's module and task; `agents`: each agent launch's task."""

    def __init__(self, path: Path, con: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews,
                 files: SlotFiles, tracker: Tracker) -> None:
        super().__init__(con, tmp_path, slot, checkouts, files, tracker)
        self.path, self.bodies, self.starts = path, list[str](), 0
        self.entries, self.launched, self.alive = list[tuple[str, str]](), list[str](), set[EntryIdentity]()
        self.checks = CheckStore(lambda: con)

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        self.launched.append(task_id)  # the agent launcher: plan and implement attempts only
        return super().launch(backlog, task_id, minutes)

    def starting(self) -> StartPorts:
        admission = ChecksAdmission(lambda: self.con, begin_immediate, self.tracker.inspect, self.checkouts, lambda: self.now,
                                    lambda _p: True, self.files, lambda path: GitProfileFiles(path, self.checkouts))
        launcher = Launcher(self.path, EvidenceFiles(self.tmp), lambda: self.now, self.entry, self.process, "python",
                            targets=CheckStore, module=CHECK_ENTRY_MODULE)
        return replace(super().starting(), checks=ChecksPorts(admission, launcher))

    def observe(self, _entry: EntryIdentity) -> Seen:
        super().observe(_entry)
        return "matching" if _entry in self.alive else "gone"

    def process(self, identity: OwnedProcess) -> ProcessObservation:
        alive = (identity.pid, identity.start, identity.boot) in self.alive
        return ProcessObservation("matching", identity) if alive else ProcessObservation("gone")

    def entry(
        self, argv: Sequence[str], *, registered: Callable[[OwnedProcess], None], cwd: object = None, env: object = None,
        stderr: int = 0, start_new_session: bool = True, registration_timeout: float = 0.0,
    ) -> tuple[Pipes, OwnedProcess]:
        """The registered start of `python -I -m taskloop.check_entry DB ARTIFACTS BACKLOG TASK`, its body run at once."""
        self.starts += 1
        body = self.bodies.pop(0)
        if body == "unstartable":
            raise OSError("no interpreter")
        identity = OwnedProcess(100 + self.starts, 100 + self.starts, f"start-{self.starts}", "boot")
        registered(identity)
        self.entries.append((argv[3], argv[-1]))
        key, me = self.key(argv[-1]), (identity.pid, identity.start, identity.boot)
        if body == "running":
            self.alive.add(me)
        elif body == "counted":
            self.checks.refused(key, "checks:running")
        elif body != "crash":
            self.conclude(key, body, me)
        return Pipes(), identity

    def key(self, task_id: str) -> AttemptKey:
        found = self.checks.attempt_of("tasks", task_id)
        assert found is not None
        return found[0]

    def conclude(self, key: AttemptKey, body: str, me: EntryIdentity) -> None:
        """The entry's conclusion, then its settled release of its own slot."""
        if body == "passed":
            self.checks.conclude(key, "passed", None, self.now)
        else:
            self.checks.conclude(key, "failed", "test:failed" if body == "failed" else body, self.now)
        released = self.releasing().release(key, False, me)
        assert isinstance(released, Released), released

    def releasing(self) -> ChecksRelease:
        return ChecksRelease(self.checks, self.checkouts, self.files, lambda _entry: "gone", custody, lambda: self.now,
                             lambda _process: "gone", lambda _scratch: True)

    def finish(self, task_id: str, body: str) -> None:
        """The running entry of the task's checks attempt ends with `body`."""
        found = self.checks.attempt_of("tasks", task_id)
        assert found is not None and found[2] is not None
        self.conclude(found[0], body, found[2])
        self.alive.discard(found[2])

    def counted(self, task_id: str) -> tuple[object, ...]:
        row = "SELECT refusal,refusals FROM checks_attempt WHERE attempt_id=?"
        return self.con.execute(row, (self.key(task_id).attempt_id,)).fetchone()

    def rows(self) -> list[tuple[object, ...]]:
        return self.con.execute("SELECT a.task_id,c.number,c.phase,c.conclusion FROM checks_attempt c JOIN attempt a "
                                "ON a.attempt_id=c.after_attempt_id ORDER BY a.task_id,c.number").fetchall()

    def logged(self, *words: str) -> int:
        """How many `rounds.log` lines end with these words."""
        return sum(1 for line in self.lines if line.split(" ")[2:] == list(words))


@pytest.fixture
def rig(tmp_path: Path, slot: FakeWorktree, checkouts: PinnedViews, slot_files: SlotFiles) -> Generator[Checking]:
    """One adopted slot, tl-1 ready with `auto`; the person's `main` requires `check` and `test` (`MAIN_PROFILE`)."""
    root = slot.repo.worktree(slot.repo.identity().root)
    root.write_file(".task-loop.json", json.dumps(MAIN_PROFILE))
    assert isinstance(root.record("profile", paths="all"), Recorded)
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    built = Checking(path, con, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1")))
    scripts(built, slot, "tl-1", "tl-2", "tl-3")
    yield built
    con.close()


def implemented(rig: Checking) -> None:
    """tl-1 planned, advanced, implemented and verified by four rounds; its check advance is next."""
    assert rig.round() == [("tl-1", "plan", "start", "started")]
    assert rig.round() == [("tl-1", "plan", "verify", "verified release=released branch=published")]
    assert rig.round() == [("tl-1", "implement", "advance", "started")]
    assert rig.round() == [("tl-1", "implement", "verify", "verified release=released branch=published")]
    assert rig.next_words() == {"tl-1": ("implement", "advance")}


def ready(rig: Checking, task_id: str) -> None:
    rig.tracker.beads[task_id] = task(task_id)


def test_rounds_take_a_task_through_plan_implement_and_its_checks_to_done_with_one_claim(rig: Checking) -> None:
    implemented(rig)
    rig.bodies = ["passed"]
    assert rig.round() == [("tl-1", "check", "advance", "started")] and rig.last.stopped == ""
    checks = rig.key("tl-1").attempt_id
    assert rig.round() == [] and rig.next_words() == {"tl-1": ("check", "done")}  # a pass writes nothing
    assert rig.entries == [(CHECK_ENTRY_MODULE, "tl-1")] and rig.launched == ["tl-1", "tl-1"]
    assert rig.rows() == [("tl-1", 1, "concluded", "passed")] and rig.tracker.claims == ["tl-1"]
    assert rig.tracker.beads["tl-1"].status == "in_progress" and rig.logged("tl-1", "check", "advance", "started", checks) == 1


def test_a_failed_check_is_reported_once_never_re_run_and_new_work_still_starts(rig: Checking) -> None:
    implemented(rig)
    rig.bodies = ["failed"]
    assert rig.round(frozenset()) == [("tl-1", "check", "advance", "started")]
    checks = rig.key("tl-1").attempt_id
    ready(rig, "tl-2")
    assert rig.round(rig.last.written) == [("tl-1", "check", "report", "failed:test:failed"), ("tl-2", "plan", "start", "started")]
    assert rig.round(rig.last.written)[0] == ("tl-1", "check", "report", "failed:test:failed")
    assert rig.logged("tl-1", "check", "report", "failed:test:failed", checks) == 1  # `quiet`: written once
    assert rig.rows() == [("tl-1", 1, "concluded", "failed")] and rig.starts == 1  # no re-run, no relaunch
    assert rig.next_words()["tl-1"] == ("check", "done") and rig.tracker.claims == ["tl-1", "tl-2"]
    assert rig.tracker.beads["tl-1"].status == "in_progress"  # the claim is kept


@pytest.mark.parametrize(("first", "advance"), [
    ("unstartable", ("tl-1", "implement", "advance", "unavailable:start")),
    ("crash", ("tl-1", "check", "advance", "started")),
    ("counted", ("tl-1", "check", "advance", "started")),
])
def test_an_admitted_checks_attempt_is_relaunched_with_the_checks_launcher_only(
    rig: Checking, first: str, advance: tuple[str, str, str, str]
) -> None:
    implemented(rig)
    rig.bodies = [first, "passed"]
    assert rig.round() == [advance]
    checks = rig.key("tl-1").attempt_id
    assert rig.next_words() == {"tl-1": ("check", "start")}
    assert rig.round() == [("tl-1", "check", "relaunch", "relaunched")] and rig.last.moves[0].attempt_id == checks
    assert rig.round() == [] and rig.next_words() == {"tl-1": ("check", "done")}
    assert {module for module, _task in rig.entries} == {CHECK_ENTRY_MODULE} and rig.launched == ["tl-1", "tl-1"]
    assert rig.rows() == [("tl-1", 1, "concluded", "passed")] and rig.logged("tl-1", "check", "relaunch", "relaunched", checks) == 1


def test_two_counted_refusals_stop_the_relaunches_without_stopping_new_work_until_a_start_by_hand(rig: Checking) -> None:
    implemented(rig)
    rig.bodies = ["counted", "counted", "passed"]
    assert rig.round() == [("tl-1", "check", "advance", "started")]
    assert rig.round() == [("tl-1", "check", "relaunch", "relaunched")]
    rig.adopt("s2")
    ready(rig, "tl-2")
    stuck = ("tl-1", "check", "report", "stuck:checks_refused")
    assert rig.round(frozenset()) == [stuck, ("tl-2", "plan", "start", "started")]
    assert rig.round(rig.last.written)[0] == stuck and rig.starts == 2 and rig.counted("tl-1") == ("checks:running", 2)
    assert rig.logged("tl-1", "check", "report", "stuck:checks_refused", rig.key("tl-1").attempt_id) == 1
    rig.now += 1
    by_hand = start(rig.starting(), StartRequest("tl-1", "tasks", "/tracker", rig.slot.repo.path, "m", "high", 30))
    assert isinstance(by_hand, Started) and (by_hand.status, by_hand.step) == ("relaunched", "check")
    assert rig.next_words()["tl-1"] == ("check", "done") and rig.counted("tl-1") == (None, 0)


@pytest.mark.parametrize(("late", "word"), [("unstartable", "unavailable:start"), ("crash", "relaunched")])
def test_relaunches_that_never_reach_the_entry_s_count_stop_after_two_past_the_deadline(rig: Checking, late: str, word: str) -> None:
    implemented(rig)
    rig.bodies = ["crash", "crash", late, late]
    assert rig.round() == [("tl-1", "check", "advance", "started")]
    assert rig.round() == [("tl-1", "check", "relaunch", "relaunched")]  # before the deadline: not counted, as an agent's
    assert rig.counted("tl-1") == (None, 0)
    rig.now += AFTER_DEADLINE
    assert rig.round() == [("tl-1", "check", "relaunch", word)] and rig.counted("tl-1") == (LATE, 1)
    assert rig.round() == [("tl-1", "check", "relaunch", word)] and rig.counted("tl-1") == (LATE, 2)
    assert rig.round() == [("tl-1", "check", "report", "stuck:checks_refused")] and rig.starts == 4 and rig.bodies == []
    assert rig.rows() == [("tl-1", 1, "admitted", None)]


def test_a_relaunch_past_the_deadline_that_concludes_expired_clears_the_count(rig: Checking) -> None:
    implemented(rig)
    rig.bodies = ["crash", "expired"]
    assert rig.round() == [("tl-1", "check", "advance", "started")]
    rig.now += AFTER_DEADLINE
    assert rig.round() == [("tl-1", "check", "relaunch", "relaunched")]
    assert rig.round() == [("tl-1", "check", "report", "failed:expired")] and rig.counted("tl-1") == (None, 0)


def test_an_abandon_during_checks_is_never_re_advanced_and_its_half_done_state_is_attempted(rig: Checking) -> None:
    implemented(rig)
    rig.bodies = ["failed"]
    rig.round()
    implement = rig.current("tl-1")
    assert isinstance(rig.releasing().release(rig.key("tl-1"), True), Released)  # the abandon's first half
    rig.tracker.beads["tl-1"] = replace(rig.tracker.beads["tl-1"], status="open", assignee="")  # and the claim lapsed
    assert rig.round() == [("tl-1", "check", "report", "release"), ("tl-1", "check", "skip", "attempted")]
    found = rig.store.attempt_of("tasks", "tl-1")
    assert found is not None and found[0].attempt_id == implement and rig.releaser().release(found[0], True)
    assert rig.round() == [("tl-1", "implement", "skip", "abandoned")]
    assert rig.rows() == [("tl-1", 1, "concluded", "failed")] and rig.starts == 1 and rig.tracker.claims == ["tl-1"]


def test_two_done_tasks_and_one_slot_check_in_release_order_before_new_work(rig: Checking) -> None:
    ready(rig, "tl-2")
    for _ in range(4):  # plan and implement both, interleaved through the one slot
        rig.round()
    assert rig.next_words() == {"tl-1": ("implement", "advance"), "tl-2": ("implement", "verify")}
    rig.bodies = ["running", "passed"]
    ready(rig, "tl-3")
    assert rig.round() == [("tl-2", "implement", "verify", "verified release=released branch=published"),
                           ("tl-1", "check", "advance", "started")]
    reads = rig.tracker.ready_reads
    assert rig.round() == [("tl-1", "check", "report", "running")] and rig.last.stopped == "no_free_slot"
    assert rig.tracker.ready_reads == reads and rig.next_words()["tl-2"] == ("implement", "advance")  # tl-2 and tl-3 wait
    rig.finish("tl-1", "passed")
    # tl-2's checks pass at once here (its entry ran within the launch), so the slot is free again for tl-3 after them
    assert rig.round() == [("tl-2", "check", "advance", "started"), ("tl-3", "plan", "start", "started")]
    assert rig.rows() == [("tl-1", 1, "concluded", "passed"), ("tl-2", 1, "concluded", "passed")]
