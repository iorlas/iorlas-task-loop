"""The step operations on a task in its check step (S6d, tl-8bh9.14.6 sections 5, 9, 10) over a factory.db file (the
`done` implement attempt), the real checks admission (`ChecksBench`) and a checks launcher that reads the store as the
real one does: `tl step start` advances, relaunches, answers, re-runs and refuses the half-done abandon; the racing
winner goes to the checks launcher; release and abandon go checks first; verify stays on the agent attempt."""

import dataclasses
from collections.abc import Generator
from pathlib import Path

import pytest
from doubles import ChecksBench, Done, FakeSlotFiles, NoAdvance, NoChecks, PinnedViews
from git_porcelain.testing import FakeRepo

from taskloop.admit import AdmitRequest, AdmitResult
from taskloop.attempt_reads import PublishedRow
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, EntryIdentity, Verified, VerifyResult
from taskloop.check_store import ChecksAdmitted, CheckStore, insert
from taskloop.launch import Launched, LaunchRefused, LaunchResult, LaunchUnavailable
from taskloop.operations import (
    LATE,
    ChecksPorts,
    Failed,
    ReleasedTask,
    Started,
    StartPorts,
    StartRequest,
    VerifiedTask,
    relaunch_checks,
    release_task,
    start,
    verify_task,
)
from taskloop.publish import PublishResult
from taskloop.slot_release import AlreadyReleased, NotReleased, Released, ReleaseResult
from taskloop.step_guide import CHECKS_GUIDE, GUIDE
from taskloop.step_render import human

ENTRY = (7, "entry-start", "boot")
REQUEST = StartRequest("tl-1", "tasks", "/tracker", Path("/unused"), "m", "high", 30)


class Never:
    """The agent admission and repeat of a start that stays in the check step."""

    def admit(self, request: AdmitRequest) -> AdmitResult:
        raise AssertionError(f"no fresh admission expected: {request.task_id}")

    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: EntryIdentity | None, minutes: int) -> Started:
        raise AssertionError("no repeat expected")


@dataclasses.dataclass
class ChecksLauncher:
    """The checks launcher, semantically: it launches the task's latest checks attempt (`CheckStore.attempt_of`, the
    real launcher's read) only while `admitted`, else refuses `dispatched`; `failing` answers instead, once."""

    store: CheckStore
    calls: list[AttemptKey] = dataclasses.field(default_factory=list)
    failing: LaunchResult | None = None

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        found = self.store.attempt_of(backlog, task_id)
        assert found is not None
        self.calls.append(found[0])
        failing, self.failing = self.failing, None
        if failing is not None:
            return failing
        return Launched(found[0], ENTRY) if found[1] == "admitted" else LaunchRefused("dispatched")


@dataclasses.dataclass
class Rig:
    bench: ChecksBench

    def __post_init__(self) -> None:
        self.launcher = ChecksLauncher(CheckStore(lambda: self.bench.con))

    def ports(self) -> StartPorts:
        reader = AttemptStore(lambda: self.bench.con)
        never = Never()
        checks = ChecksPorts(self.bench.admission(), self.launcher, NoChecks())
        return StartPorts(reader, never, NoChecks(), lambda: 10, never, NoAdvance(), checks)

    def start(self, advancing: str | None = None) -> Started | Failed:
        return start(self.ports(), dataclasses.replace(REQUEST, checkout=self.bench.repo.path), advancing=advancing)

    def numbers(self) -> list[tuple[object, ...]]:
        return self.bench.con.execute("SELECT number,phase FROM checks_attempt ORDER BY number").fetchall()


@pytest.fixture
def rig(done: Done, repo: FakeRepo, checkouts: PinnedViews, slot_files: FakeSlotFiles) -> Generator[Rig]:
    bench = ChecksBench(done, repo, checkouts, slot_files)
    yield Rig(bench)
    bench.con.close()


def test_start_on_a_done_implement_attempt_admits_checks_and_launches_them_with_the_checks_launcher(rig: Rig) -> None:
    started = rig.start()
    assert isinstance(started, Started) and (started.status, started.step, started.existing) == ("started", "check", False)
    assert rig.numbers() == [(1, "admitted")] and [key.attempt_id for key in rig.launcher.calls] == [started.attempt_id]
    again = rig.start()  # its entry gone: relaunched, never admitted twice
    assert isinstance(again, Started) and (again.status, again.step, again.attempt_id) == ("relaunched", "check", started.attempt_id)
    assert rig.numbers() == [(1, "admitted")] and len(rig.launcher.calls) == 2


@pytest.mark.parametrize(("conclusion", "released", "result"), [
    ("passed", True, "passed"), ("passed", False, "passed"), ("failed", False, "failed:test:failed"),
])
def test_a_concluded_checks_attempt_is_answered_and_never_launched(rig: Rig, conclusion: str, released: bool, result: str) -> None:
    first = rig.start()
    rig.bench.concluded(conclusion, released=released)
    found = rig.start()
    assert isinstance(found, Started) and (found.status, found.result, found.step) == ("already_dispatched", result, "check")
    assert isinstance(first, Started) and found.attempt_id == first.attempt_id and len(rig.launcher.calls) == 1


def test_a_failed_released_checks_attempt_is_re_run_by_start_but_never_by_the_round(rig: Rig) -> None:
    first = rig.start()
    assert isinstance(first, Started)
    rig.bench.concluded("failed")
    by_round = rig.start(advancing="implement")
    assert isinstance(by_round, Failed) and by_round.word == "refused:changed" and rig.numbers() == [(1, "concluded")]
    rerun = rig.start()
    assert isinstance(rerun, Started) and (rerun.status, rerun.step) == ("started", "check") and rerun.attempt_id != first.attempt_id
    assert rig.numbers() == [(1, "concluded"), (2, "admitted")] and rig.launcher.calls[-1].attempt_id == rerun.attempt_id


def test_the_round_advances_only_a_done_implement_attempt_with_no_checks_attempt(rig: Rig) -> None:
    advanced = rig.start(advancing="implement")
    assert isinstance(advanced, Started) and advanced.step == "check"
    relaunch = rig.start(advancing="implement")  # an admitted checks attempt is the settle phase's, not an advance
    assert isinstance(relaunch, Failed) and relaunch.word == "refused:changed" and len(rig.launcher.calls) == 1


def test_the_half_done_abandon_refuses_release_and_launches_nothing(rig: Rig) -> None:
    rig.start()
    rig.bench.concluded("failed", abandoned=True)
    found = rig.start()
    assert isinstance(found, Failed) and found.word == "refused:release" and "--abandon" in found.detail
    assert rig.numbers() == [(1, "concluded")] and len(rig.launcher.calls) == 1


def test_a_racing_winner_is_launched_with_the_checks_launcher(rig: Rig) -> None:
    def winner() -> None:
        with rig.bench.begin(rig.bench.con):
            rig.bench.con.execute("INSERT INTO reservation VALUES ('s0',?,7,'winner')", (rig.bench.repo.identity().key,))
            insert(rig.bench.con, ChecksAdmitted(AttemptKey("winner", "w", 7), "implement", 1, "s0", rig.bench.done.d,
                                                 rig.bench.done.target, (("check", "1" * 64),), 100.0))

    rig.bench.racing = winner  # committed between the admission's reads and its write
    found = rig.start()
    assert isinstance(found, Started)
    assert (found.status, found.attempt_id, found.existing, found.step) == ("relaunched", "winner", True, "check")
    assert rig.launcher.calls == [AttemptKey("winner", "w", 7)] and rig.numbers() == [(1, "admitted")]


def test_a_launch_failure_after_the_admission_says_admitted_and_the_next_start_relaunches(rig: Rig) -> None:
    rig.launcher.failing = LaunchUnavailable("start")
    found = rig.start()
    assert isinstance(found, Failed) and found.word == "unavailable:start" and found.admitted
    again = rig.start()
    assert isinstance(again, Started) and again.status == "relaunched" and rig.numbers() == [(1, "admitted")]


@dataclasses.dataclass
class Releases:
    """A release port that records each (attempt, abandon) and answers `results` in order (default released)."""

    calls: list[tuple[str, bool]] = dataclasses.field(default_factory=list)
    results: list[ReleaseResult] = dataclasses.field(default_factory=list)

    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        self.calls.append((key.attempt_id, abandon))
        return self.results.pop(0) if self.results else Released("s1", None, True, "kept", abandon)


def release(rig: Rig, abandon: bool, implement: Releases, checks: Releases) -> ReleasedTask | Failed:
    return release_task(AttemptStore(lambda: rig.bench.con), implement, checks, "tasks", "tl-1", abandon=abandon)


def test_a_settled_release_of_a_task_in_check_releases_only_its_checks_attempt(rig: Rig) -> None:
    started = rig.start()
    assert isinstance(started, Started)
    implement, checks = Releases(), Releases()
    found = release(rig, False, implement, checks)
    assert isinstance(found, ReleasedTask) and found.attempt_id == started.attempt_id and found.checks is None
    assert checks.calls == [(started.attempt_id, False)] and implement.calls == []


def test_the_abandon_goes_checks_first_then_returns_the_claim_through_the_implement_attempt(rig: Rig) -> None:
    started = rig.start()
    assert isinstance(started, Started)
    implement, checks = Releases(results=[Released("s0", None, False, "unclaimed", True)]), Releases()
    found = release(rig, True, implement, checks)
    assert checks.calls == [(started.attempt_id, True)] and implement.calls == [("implement", True)]
    assert isinstance(found, ReleasedTask) and (found.attempt_id, found.result.claim) == ("implement", "unclaimed")
    assert found.checks == ReleasedTask("tasks", "tl-1", started.attempt_id, Released("s1", None, True, "kept", True))


@pytest.mark.parametrize(("checks_result", "implement_result", "word", "implement_called"), [
    (NotReleased("refused", "entry_running", "runs"), None, "refused:entry_running", False),
    (None, NotReleased("unavailable", "changed", "Changed."), "unavailable:changed", True),
], ids=["checks_held", "implement_failed"])
def test_an_abandon_that_stops_half_way_says_so_and_its_rerun_finishes(
    rig: Rig, checks_result: NotReleased | None, implement_result: NotReleased | None, word: str, implement_called: bool
) -> None:
    rig.start()
    checks = Releases(results=[] if checks_result is None else [checks_result])
    implement = Releases(results=[] if implement_result is None else [implement_result])
    found = release(rig, True, implement, checks)
    assert isinstance(found, Failed) and found.word == word and bool(implement.calls) is implement_called
    assert implement_result is None or found.detail.endswith("The checks attempt was released first.")
    rerun = release(rig, True, Releases(results=[AlreadyReleased("s0", "unclaimed", True)]), Releases())
    assert isinstance(rerun, ReleasedTask) and rerun.checks is not None


def test_a_check_still_running_is_guided_as_a_checks_attempt_never_with_the_agent_slot_guide(rig: Rig) -> None:
    rig.start()
    held = NotReleased("unsettled", "check_running", "The check slow (process group 9) still runs")
    found = release(rig, False, Releases(), Releases(results=[held]))
    assert isinstance(found, Failed) and found.word == "unsettled:check_running" and found.checks
    lines = human("release", found, None)
    assert CHECKS_GUIDE["unsettled"] in lines and GUIDE["check_running"] in lines and GUIDE["unsettled"] not in lines


def test_without_a_checks_attempt_the_release_is_the_implement_attempt_s(rig: Rig) -> None:
    implement, checks = Releases(results=[AlreadyReleased("s0", "kept", False)]), Releases()
    found = release(rig, False, implement, checks)
    assert isinstance(found, ReleasedTask) and found.attempt_id == "implement" and checks.calls == []


@dataclasses.dataclass
class Recorded:
    """Verify and publish ports that record the attempt they were asked about: a stored verdict, an earlier publication."""

    commit: str
    keys: list[str] = dataclasses.field(default_factory=list)

    def verify(self, key: AttemptKey) -> VerifyResult:
        self.keys.append(key.attempt_id)
        return Verified("blob", reused=True)

    def publish(self, key: AttemptKey) -> PublishResult:
        self.keys.append(key.attempt_id)
        return PublishedRow(self.commit, self.commit, 6)


def test_verify_on_a_task_in_check_acts_on_its_implement_attempt_only(rig: Rig) -> None:
    rig.start()
    seen, implement = Recorded(rig.bench.done.x), Releases(results=[AlreadyReleased("s0", "kept", False)])
    found = verify_task(AttemptStore(lambda: rig.bench.con), seen, implement, seen, "tasks", "tl-1")
    assert isinstance(found, VerifiedTask) and (found.status, found.attempt_id) == ("reused", "implement")
    assert seen.keys == ["implement", "implement"] and implement.calls == [("implement", False)]


@pytest.mark.parametrize("abandon", [False, True], ids=["settled", "abandon_rerun"])
def test_after_a_finished_abandon_the_release_is_the_implement_attempt_s_with_its_returned_claim(rig: Rig, abandon: bool) -> None:
    rig.start()
    rig.bench.concluded("failed", abandoned=True)
    rig.bench.con.execute("UPDATE slot_release SET claim='unclaimed'")
    implement, checks = Releases(results=[AlreadyReleased("s0", "unclaimed", True)]), Releases()
    found = release(rig, abandon, implement, checks)
    assert isinstance(found, ReleasedTask) and (found.attempt_id, found.result.claim, found.checks) == ("implement", "unclaimed", None)
    assert checks.calls == [] and implement.calls == [("implement", abandon)]


def test_a_checks_attempt_admitted_after_the_implement_flip_is_still_released_first(rig: Rig) -> None:
    """The other race order: the claim is no longer `kept`, but the latest checks attempt holds its slot."""
    started = rig.start()
    assert isinstance(started, Started)
    rig.bench.con.execute("UPDATE slot_release SET claim='unclaiming'")
    implement, checks = Releases(results=[Released("s0", None, False, "unclaimed", True)]), Releases()
    found = release(rig, True, implement, checks)
    assert checks.calls == [(started.attempt_id, True)] and isinstance(found, ReleasedTask) and found.checks is not None


def relaunch(rig: Rig, attempt_id: str, now: float = 10) -> Started | Failed:
    return relaunch_checks(dataclasses.replace(rig.ports(), clock=lambda: now), "tasks", "tl-1", attempt_id, 30)


def test_the_round_s_relaunch_launches_the_snapshot_s_admitted_checks_attempt_with_the_checks_launcher(rig: Rig) -> None:
    first = rig.start()
    assert isinstance(first, Started)
    found = relaunch(rig, first.attempt_id)
    assert isinstance(found, Started) and (found.status, found.step, found.attempt_id) == ("relaunched", "check", first.attempt_id)
    assert len(rig.launcher.calls) == 2 and rig.bench.con.execute("SELECT refusals FROM checks_attempt").fetchone() == (0,)


@pytest.mark.parametrize(("state", "word"), [
    ("other", "refused:changed"), ("concluded", "refused:concluded"), ("released", "refused:released"),
    ("abandoned", "refused:abandoned"), ("unreserved", "refused:stale_reservation"),
])
def test_the_round_s_relaunch_is_fenced_on_the_checks_store_and_launches_nothing_else(rig: Rig, state: str, word: str) -> None:
    first = rig.start()
    assert isinstance(first, Started)
    if state in ("concluded", "released", "abandoned"):
        rig.bench.concluded("passed", released=state != "concluded", abandoned=state == "abandoned")
    if state == "unreserved":
        rig.bench.con.execute("DELETE FROM reservation")
    found = relaunch(rig, "another" if state == "other" else first.attempt_id, now=10_000)  # past the deadline
    assert isinstance(found, Failed) and found.word == word and len(rig.launcher.calls) == 1


def test_a_relaunch_past_the_deadline_is_counted_before_the_launch_whatever_the_launch_does(rig: Rig) -> None:
    first = rig.start()
    assert isinstance(first, Started)
    rig.launcher.failing = LaunchUnavailable("start")
    found = relaunch(rig, first.attempt_id, now=10_000)
    assert isinstance(found, Failed) and found.word == "unavailable:start"
    assert rig.bench.con.execute("SELECT refusal,refusals FROM checks_attempt").fetchone() == (LATE, 1)
