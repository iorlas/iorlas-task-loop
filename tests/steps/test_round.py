"""One scheduling round (`round.run_round`) over a real in-memory factory.db: recording admission, launch, repeat,
verify, release and publish ports where the round itself is under test (the real ones where a row needs a stored verdict),
beads-client's seeded ready set, a fake clock and entry observation, and a list as the round log. No process starts."""

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from beads_client import BdError, Bead
from doubles import NO_CHECKS, NoAdvance, NoChecks, ReadyTracker, no_holds
from git_porcelain.testing import FakeWorktree

from taskloop.admit import AdmitRefused, AdmitRequest, AdmitResult, Admitted, AdmitUnavailable
from taskloop.admit_chain import NextStepRequest
from taskloop.agents.launch import AgentLaunch
from taskloop.agents.settings import Overrides, StepSettings
from taskloop.attempt import Attempts
from taskloop.attempt_status import StatusPorts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, Checkouts, EntryIdentity, Seen, SlotFiles, Unsettled, Verified, VerifyResult
from taskloop.evidence_files import EvidenceFiles
from taskloop.exit_codes import exit_code
from taskloop.hold import HoldPorts
from taskloop.hold_store import HoldInsert, HoldStore
from taskloop.ids import NativeIds
from taskloop.launch import Launched, LaunchRefused, LaunchResult, LaunchUnavailable, LaunchUncertain
from taskloop.operations import (
    Advance,
    Failed,
    Move,
    Publish,
    Release,
    Round,
    Started,
    StartPorts,
    VerifiedTask,
    Verify,
    verify_task,
)
from taskloop.publish import BranchPublish, BranchPublished, NotPublished, PublishResult
from taskloop.round import NextRequest, RoundPorts, never, run_round
from taskloop.slot_lock import custody, hold
from taskloop.slot_release import NotReleased, Released, ReleaseResult, SlotRelease
from taskloop.slots import SlotView
from taskloop.step_render import human
from taskloop.tracker import leaked_claim
from taskloop.verifier import Verifier

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
BEFORE_REBOOT = (7, "entry-start", "old-boot")  # registered in another boot than the bench's "boot"
HEAD, X = "d" * 40, "x" * 40
REQUEST = NextRequest(
    "tasks", "/tracker", Path("/checkout"), "auto", StepSettings(), Overrides(model="model-m", effort="high"), 30, max_running=10
)
STAMP = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ tasks "
STEPPED = r"\S+ plan (start|relaunch|repeat|verify|publish|report|skip)( \S+)+"  # every attempt-bearing move names its step
LINE = re.compile(STAMP + rf"({STEPPED}|\S+ (start|report) (refused|unavailable|claim_leaked)\S*|round( \S+)+)")


def bead(task_id: str, priority: int | None = 2, parent: str = "", assignee: str = "") -> Bead:
    return Bead(task_id, priority=priority, parent=parent, assignee=assignee, labels=("auto",))


class Admission:
    """Admits each requested task (`refusals` per task id instead); `effect` runs after each admission, as its rows."""

    def __init__(self, refusals: dict[str, AdmitResult] | None = None, effect: Callable[[str], object] = lambda _task: None) -> None:
        self.refusals, self.effect = refusals or {}, effect
        self.requests: list[str] = []

    def admit(self, request: AdmitRequest) -> AdmitResult:
        self.requests.append(request.task_id)
        if request.task_id in self.refusals:
            return self.refusals[request.task_id]
        self.effect(request.task_id)
        return Admitted(AttemptKey(f"a-{request.task_id}", f"token-{request.task_id}", 1), "s1")


class FakeLauncher:
    """Launches each task's entry (`results` per task id instead)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.minutes: list[int] = []
        self.results: dict[str, LaunchResult] = {}

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        self.calls.append(task_id)
        self.minutes.append(minutes)
        return self.results.get(task_id, Launched(KEY, ENTRY))


class Repeats:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: EntryIdentity | None, minutes: int) -> Started | Failed:
        self.calls.append(task_id)
        return Started("repeated", backlog, task_id, "next", False, ENTRY, number=2)


class Advances:
    """The advance port answering `result` to every request it records."""

    def __init__(self, result: AdmitResult) -> None:
        self.result = result
        self.requests: list[NextStepRequest] = []

    def admit_next(self, request: NextStepRequest) -> AdmitResult:
        self.requests.append(request)
        return self.result


PARKED = Released("s1", HEAD, True, "kept", False)


class Recorded:
    """The verify, release and publish ports, each recording the attempt it was called for."""

    def __init__(self, release: ReleaseResult = PARKED) -> None:
        self.calls: list[str] = []
        self.released = release

    def verify(self, key: AttemptKey) -> VerifyResult:
        self.calls.append("verify")
        return Verified("blob")

    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        self.calls.append("release")
        return self.released

    def publish(self, key: AttemptKey) -> PublishResult:
        self.calls.append("publish")
        return BranchPublished(X, X)


class Bench:
    """The round's ports over one factory.db connection; `now`, `seen` and `left` steer the reads. `free`: one more adopted
    slot (another repo's) without a reservation row, so the free-slot read lets admission read the tracker."""

    def __init__(
        self, con: sqlite3.Connection, ready: ReadyTracker | None = None, admission: Admission | None = None, *, free: bool = True,
    ) -> None:
        if free:
            con.execute("INSERT OR IGNORE INTO slot (repo_id,name,path) VALUES ('other','s1','/other/s1')")
        self.store, self.ready = AttemptStore(lambda: con), ready or ReadyTracker()
        self.admission, self.launcher, self.repeats, self.recorded = admission or Admission(), FakeLauncher(), Repeats(), Recorded()
        self.now = 10.0
        self.during: Callable[[], object] = lambda: None
        self.seen: Seen = "gone"
        self.left: Unsettled | None = None
        self.lines: list[str] = []
        self.log: Callable[[str], None] = self.lines.append
        self.verifier: Verify = self.recorded
        self.releaser: Release = self.recorded
        self.publisher: Publish = self.recorded
        self.stopping: Callable[[], bool] = never
        self.advance: Advance = NoAdvance()

    def observe(self, _entry: EntryIdentity) -> Seen:
        """Called while the round reads its snapshot: `during` is another actor acting right after that read."""
        self.during()
        return self.seen

    def leftovers(self, _key: AttemptKey) -> Unsettled | None:
        return self.left

    def ports(self) -> RoundPorts:
        reads = StatusPorts(self.store, self.observe, lambda: self.now, self.leftovers, lambda: "boot")
        starting = StartPorts(self.store, self.admission, self.launcher, lambda: self.now, self.repeats, self.advance, NO_CHECKS)
        holding = HoldPorts(HoldStore(self.store.connect), self.store, no_holds(), self.releaser, NoChecks(), lambda: self.now,
                            EvidenceFiles(Path("/artifacts")), lambda _backlog, _task: None)  # no label here: nothing is held
        return RoundPorts(reads, starting, self.verifier, self.releaser, self.publisher, holding, self.ready,
            self.log, self.stopping, ids=NativeIds())

    def round(self, request: NextRequest = REQUEST) -> Round:
        found = run_round(self.ports(), request)
        assert isinstance(found, Round)
        return found


def seed(con: sqlite3.Connection, task_id: str, attempt_id: str, *, phase: str = "admitted", entry: EntryIdentity | None = None) -> None:
    """One attempt of `tasks/<task_id>` (deadline 100), with its registered entry when given."""
    con.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,
        input_digest,schema_version,model,effort,access_policy,deadline,entry_pid,entry_start,entry_boot,phase,base_commit,
        number,seq,slot_head)
        VALUES (?,?,1,'plan','beads','tasks',?,'/tracker','repo','s1','input.txt','digest',1,'m','high','{"harness":"codex",
        "sandbox":"workspace-write"}',
        100,?,?,?,?,?,1,1,?)""",
        (attempt_id, f"token-{attempt_id}", task_id, *(entry or (None, None, None)), phase, None if phase == "admitted" else HEAD, HEAD),
    )


def released(con: sqlite3.Connection, attempt_id: str, claim: str) -> None:
    con.execute("INSERT INTO slot_release VALUES (?,?,1,?,5,?)", (attempt_id, f"token-{attempt_id}", HEAD, claim))


def held(con: sqlite3.Connection, attempt_id: str) -> None:
    """The attempt's hold, finished with a label word that is no answer (`not_ours`): the factory abandoned it and only a person's
    answer takes it again; the round skips it as `abandoned`."""
    con.execute("UPDATE attempt SET label='auto' WHERE attempt_id=?", (attempt_id,))  # only a round-taken attempt is held
    store = HoldStore(lambda: con)
    row = store.labelled(attempt_id, store.insert(HoldInsert(attempt_id, attempt_id, "stuck:expired_admitted", 10.0)).rev, "not_ours", 11.0)
    leased = store.commenting(attempt_id, row.rev, 12.0)
    assert leased is not None
    store.commented(attempt_id, leased.rev, 13.0)


def moves(found: Round) -> list[tuple[str, str, str]]:
    return [(each.task_id, each.action, each.word) for each in found.moves]


@pytest.mark.parametrize("phase, entry, seen, now, claim, expected, launched", [
    ("admitted", None, "gone", 10, None, ("relaunch", "relaunched"), 1),
    ("admitted", ENTRY, "gone", 10, None, ("relaunch", "relaunched"), 1),
    ("admitted", ENTRY, "different_process", 10, None, ("relaunch", "relaunched"), 1),
    ("admitted", ENTRY, "matching", 10, None, ("report", "running"), 0),
    ("admitted", ENTRY, "gone", 200, None, ("report", "stuck:expired_admitted"), 0),
    ("admitted", BEFORE_REBOOT, "different_process", 200, None, ("relaunch", "relaunched"), 1),
    ("dispatching", BEFORE_REBOOT, "different_process", 200, None, ("report", "stuck:entry_lost"), 0),
    ("admitted", ENTRY, "unknown", 10, None, ("report", "unknown"), 0),
    ("dispatching", ENTRY, "gone", 10, None, ("report", "stuck:entry_lost"), 0),
    ("registered", ENTRY, "matching", 200, None, ("report", "stuck:hung"), 0),
    ("admitted", None, "gone", 10, "unclaimed", None, 0),
    ("admitted", None, "gone", 10, "unclaiming", ("report", "release"), 0),
])
def test_each_existing_attempt_by_its_next_word(
    factory: sqlite3.Connection, phase: str, entry: EntryIdentity | None, seen: Seen, now: float, claim: str | None,
    expected: tuple[str, str] | None, launched: int,
) -> None:
    seed(factory, "tl-1", "attempt", phase=phase, entry=entry)
    if claim is not None:
        released(factory, "attempt", claim)
    bench = Bench(factory)
    bench.seen, bench.now = seen, now
    found = bench.round()
    assert moves(found) == ([] if expected is None else [("tl-1", *expected)])
    assert (bench.launcher.calls, bench.launcher.minutes) == (["tl-1"] * launched, [30] * launched)
    assert bench.admission.requests == bench.repeats.calls == bench.recorded.calls == []
    assert exit_code(found) == (3 if expected == ("report", "unknown") else 0)


def test_an_admitted_attempt_is_relaunched_each_round_until_its_deadline(factory: sqlite3.Connection) -> None:
    seed(factory, "tl-1", "attempt", entry=ENTRY)
    bench = Bench(factory)
    first, second = bench.round(), bench.round()
    assert first.moves == second.moves == (Move("tl-1", "relaunch", "relaunched", "attempt", step="plan"),)
    bench.now = 200
    assert moves(bench.round()) == [("tl-1", "report", "stuck:expired_admitted")]
    assert bench.launcher.calls == ["tl-1", "tl-1"]
    assert bench.lines[0].endswith(" tasks tl-1 plan relaunch relaunched attempt") and bench.lines[1].endswith(" tasks round moves=1")


def captured(con: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles, rc: int = 0) -> None:
    """The registered attempt's step ran: a valid planned answer (rc 0) or a failed run, captured as the entry would."""
    path = "docs/design/tl-1/plan.md"

    def agent(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        slot.write_file(path, "# Plan\n")
        text = json.dumps({"disposition": "planned", "plan_path": path, "paths": [path], "message": "Plan", "explanation": "done"})
        worker = Worker(pid=42, pgid=42, start="native-start", boot="boot")
        outcome = RunOutcome(rc=rc, worker=worker, summary=Summary(text=text if rc == 0 else "", rc=rc, stands=True))
        return FakeRun(outcome)(harness, spec, timeout, hooks)

    store = AttemptStore(lambda: con)
    Attempts(
        store, EvidenceFiles(tmp_path), AgentLaunch(lambda _harness: ("/bin/codex", {}), ids=NativeIds()),
            agent, lambda: 10, checkouts, slot_files
    ).execute(KEY, ENTRY)


@pytest.mark.parametrize("case, expected, calls", [
    ("verify", ("verify", "verified release=released branch=published"), ["verify", "release", "publish"]),
    ("repeat", ("repeat", "repeated"), []),
    ("repeats_exhausted", ("report", "repeats_exhausted"), []),
    ("failed", ("report", "failed:run:worker_failed"), []),
    ("held", ("report", "release"), []),
])
def test_a_step_that_ran_is_verified_repeated_or_reported_every_round(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles,
    case: str, expected: tuple[str, str], calls: list[str],
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, rc=1 if case in ("failed", "held") else 0)
    bench = Bench(registered)
    if case in ("repeat", "repeats_exhausted"):
        bench.left = Unsettled("uncommitted", ("?? docs/design/tl-1/x.md",))
    if case == "repeats_exhausted":
        registered.execute("UPDATE attempt SET seq=2")
        seed(registered, "tl-1", "older", phase="captured")
        registered.execute(
            "UPDATE attempt SET number=3,previous_attempt_id='older',repeat_reason='uncommitted' WHERE attempt_id='attempt'"
        )
    if case == "failed":
        registered.execute("DELETE FROM reservation")
        released(registered, "attempt", "kept")
    rounds = [bench.round() for _ in range(1 if case == "verify" else 2)]
    assert all(moves(each) == [("tl-1", *expected)] for each in rounds)  # a failure is reported every round, never retried
    assert bench.recorded.calls == calls
    assert bench.repeats.calls == (["tl-1", "tl-1"] if case == "repeat" else [])
    assert bench.launcher.calls == bench.admission.requests == []


def verified_released(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> AttemptStore:
    """The registered attempt verified (its own publication stubbed), then released: `Next: publish`."""
    captured(registered, tmp_path, slot, checkouts, slot_files)
    store = AttemptStore(lambda: registered)
    verifier = Verifier(store, checkouts, slot_files, lambda _worker: True, lambda: 20, hold, ids=NativeIds())
    held = Recorded(NotReleased("unavailable", "slot_busy"))
    checked = verify_task(store, verifier, held, held, "tasks", "tl-1")  # its own publication is the recording stub's
    assert isinstance(checked, VerifiedTask) and checked.release == "unavailable:slot_busy"
    real = SlotRelease(store, checkouts, slot_files, lambda _entry: "gone", lambda _worker: True, custody, lambda _r, _t: True, lambda: 30,
                       lambda _setup: "gone", lambda _scratch: True, ids=NativeIds())
    assert isinstance(real.release(KEY, False), Released)
    return store


def test_a_verified_released_plan_is_published_once_then_advanced_never_before(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    store = verified_released(registered, tmp_path, slot, checkouts, slot_files)
    bench = Bench(registered)
    bench.publisher = BranchPublish(store, checkouts, slot_files, lambda: 40, ids=NativeIds())
    assert bench.round().moves == (Move("tl-1", "publish", "published", "attempt", step="plan"),)  # unpublished: no advance
    assert registered.execute("SELECT count(*) FROM published_branch").fetchone() == (1,)
    bench.advance = advances = Advances(AdmitRefused("claim_lost", detail="status open"))  # nothing pushed again: next round advances
    found = bench.round()
    assert found.moves == (Move("tl-1", "skip", "claim_lost", "attempt", "status open", "plan"),) and exit_code(found) == 0
    assert [request.previous.attempt_id for request in advances.requests] == ["attempt"] and bench.launcher.calls == []
    assert bench.lines[-2].endswith(" tasks tl-1 plan skip claim_lost attempt")


@pytest.mark.parametrize("answer, expected, stopped, code", [
    (AdmitRefused("not_advanceable"), [("tl-1", "skip", "not_advanceable")], "", 0),
    (AdmitRefused("branch_moved"), [("tl-1", "skip", "branch_moved")], "", 0),
    (AdmitRefused("branch_diverged"), [("tl-1", "skip", "branch_diverged")], "", 0),
    (AdmitRefused("no_free_slot"), [], "no_free_slot", 0),
    (AdmitUnavailable("tracker"), [("tl-1", "advance", "unavailable:tracker")], "unavailable:tracker", 3),
    *[(AdmitRefused(reason), [("tl-1", "skip", reason)], "", 0) for reason in ("task", "task_missing", "checkout", "input", "constraint")],
    (AdmitRefused("deadline"), [("tl-1", "advance", "refused:deadline")], "refused:deadline", 1),
], ids=lambda value: getattr(value, "reason", getattr(value, "what", None)))
def test_an_advance_refusal_is_a_skip_of_the_done_step_and_a_stop_word_ends_admission_too(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles,
    answer: AdmitResult, expected: list[tuple[str, str, str]], stopped: str, code: int,
) -> None:
    """The advance carries the round's checkout and choices and no label; a refusal about the task, also one from its
    stored facts (`task`, `checkout`, `input`, `constraint`), skips it and admission goes on to the ready task; a round-wide
    word (`no_free_slot`, `deadline`, an unknown) ends the advance and admission (no ready read)."""
    store = verified_released(registered, tmp_path, slot, checkouts, slot_files)
    assert isinstance(BranchPublish(store, checkouts, slot_files, lambda: 40, ids=NativeIds()).publish(KEY), BranchPublished)
    ready = ReadyTracker([bead("t-9")], ready=["t-9"])
    bench = Bench(registered, ready)
    bench.advance = advances = Advances(answer)
    found = bench.round(replace(REQUEST, quiet=frozenset()))
    assert (moves(found), found.stopped, exit_code(found)) == (expected + ([("t-9", "start", "started")] if not stopped else []), stopped,
                                                               code)
    sent = advances.requests[0]
    assert (sent.previous, sent.checkout, sent.setting.model, sent.setting.effort, sent.deadline) == (
        KEY,
        Path("/checkout"),
        "model-m",
        "high",
        1810,
    )
    assert ready.ready_reads == ([] if stopped else ["auto"]) and bench.launcher.calls == ([] if stopped else ["t-9"])
    lines = len(bench.lines)
    bench.round(replace(REQUEST, quiet=found.written))
    assert len(bench.lines) == lines and len(advances.requests) == 2  # tried again next round, its unchanged line not written


def test_with_every_slot_reserved_a_done_step_waits_without_a_tracker_read(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    store = verified_released(registered, tmp_path, slot, checkouts, slot_files)
    assert isinstance(BranchPublish(store, checkouts, slot_files, lambda: 40, ids=NativeIds()).publish(KEY), BranchPublished)
    seed(registered, "tl-2", "other", entry=ENTRY)
    registered.execute("INSERT INTO reservation VALUES ('s1',?,2,'other')", (slot.repo.identity().key,))
    bench = Bench(registered, free=False)
    bench.seen, bench.advance = "matching", (advances := Advances(AdmitRefused("claim_lost")))
    found = bench.round()
    assert moves(found) == [("tl-2", "report", "running")] and found.stopped == "no_free_slot" and advances.requests == []


def test_a_failed_publication_is_retried_every_round(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    verified_released(registered, tmp_path, slot, checkouts, slot_files)
    bench = Bench(registered)
    bench.publisher = Failing()
    rounds = [bench.round(), bench.round()]
    assert all(each.moves == (Move("tl-1", "publish", "unavailable:remote", "attempt", "no route", "plan"),) for each in rounds)
    assert all(exit_code(each) == 3 for each in rounds) and bench.publisher.calls == 2


class Failing:
    def __init__(self) -> None:
        self.calls = 0

    def publish(self, key: AttemptKey) -> PublishResult:
        self.calls += 1
        return NotPublished("unavailable", "remote", "no route")


def test_admission_follows_selection_and_stops_at_no_free_slot(factory: sqlite3.Connection) -> None:
    ready = ReadyTracker([bead("t-1"), bead("t-2", 0), bead("t-3", 1)], ready=["t-1", "t-2", "t-3"])
    admission = Admission({"t-3": AdmitRefused("no_free_slot"), "t-1": AdmitRefused("no_free_slot")})  # one free slot
    found = Bench(factory, ready, admission).round()
    assert moves(found) == [("t-2", "start", "started")] and found.stopped == "no_free_slot"
    assert admission.requests == ["t-2", "t-3"]  # t-1 never reached: never claimed
    assert ready.ready_reads == ["auto"] and exit_code(found) == 0


@pytest.mark.parametrize("refusal", [AdmitRefused(reason, detail="bd said: secret detail") for reason in (
    "claimed_elsewhere", "branch_diverged", "branch_held")], ids=lambda refusal: refusal.reason)
def test_a_refusal_about_one_task_moves_on_to_the_next(factory: sqlite3.Connection, refusal: AdmitRefused) -> None:
    ready = ReadyTracker([bead("t-1", 0), bead("t-2", 1)], ready=["t-1", "t-2"])
    admission = Admission({"t-1": refusal})
    reason = refusal.reason
    bench = Bench(factory, ready, admission)
    found = bench.round()
    assert moves(found) == [("t-1", "start", f"refused:{reason}"), ("t-2", "start", "started")]
    assert found.moves[0].detail == "bd said: secret detail" and found.stopped == "" and exit_code(found) == 0
    assert not any("secret" in line for line in bench.lines)


def test_a_refusal_naming_a_slot_on_the_task_branch_is_also_reported_unusable_in_the_log(factory: sqlite3.Connection) -> None:
    held = SlotView("s1", Path("/slots/s1"), "unknown", "attached")
    bench = Bench(factory, ReadyTracker([bead("t-1")], ready=["t-1"]), Admission({"t-1": AdmitRefused("branch_held", (held,))}))
    found = bench.round()
    assert moves(found)[:2] == [("t-1", "start", "refused:branch_held"), ("t-1", "report", "unusable:s1:attached")]
    assert found.moves[1].detail == "/slots/s1"


def test_an_advance_refused_branch_held_reports_the_slot_unusable_too(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    store = verified_released(registered, tmp_path, slot, checkouts, slot_files)
    assert isinstance(BranchPublish(store, checkouts, slot_files, lambda: 40, ids=NativeIds()).publish(KEY), BranchPublished)
    held = SlotView("s1", Path("/slots/s1"), "unknown", "attached")
    bench = Bench(registered, ReadyTracker())
    bench.advance = Advances(AdmitRefused("branch_held", (held,)))
    assert ("tl-1", "report", "unusable:s1:attached") in moves(bench.round())


@pytest.mark.parametrize("fault, stopped, code", [
    (BdError("timeout", "bd failed"), "unavailable:tracker", 3), (BdError("malformed", "bd failed"), "refused:tracker", 1),
])
def test_a_failed_ready_read_stops_admission_but_settling_still_ran(
    factory: sqlite3.Connection, fault: BdError, stopped: str, code: int
) -> None:
    seed(factory, "tl-1", "attempt")
    bench = Bench(factory, ReadyTracker(ready_fault=fault))
    found = bench.round()
    assert moves(found) == [("tl-1", "relaunch", "relaunched")] and found.stopped == stopped
    assert exit_code(found) == code and bench.admission.requests == []
    assert bench.lines[-1].endswith(f" tasks round moves=1 stopped={stopped}")


@pytest.mark.parametrize("label, minutes, model, effort, reason", [
    (" ", 30, "m", "high", "label"), ("auto", 0, "m", "high", "choices"), ("auto", 7 * 24 * 60 + 1, "m", "high", "choices"),
])
def test_an_empty_label_a_bad_choice_or_minutes_out_of_range_are_refused_before_any_read(
    factory: sqlite3.Connection, label: str, minutes: int, model: str, effort: str, reason: str
) -> None:
    seed(factory, "tl-1", "attempt", entry=ENTRY)
    ready = ReadyTracker([bead("t-1")], ready=["t-1"])
    bench = Bench(factory, ready)
    found = run_round(
        bench.ports(),
        NextRequest("tasks", "/tracker", Path("/checkout"), label, StepSettings(), Overrides(model=model, effort=effort), minutes),
    )
    assert isinstance(found, Failed) and (found.kind, found.reason) == ("refused", reason) and exit_code(found) == 1
    assert ready.ready_reads == [] and bench.lines == [] and bench.launcher.calls == []


def test_a_task_a_person_abandoned_is_restarted_only_while_the_tracker_lists_it_under_the_label(factory: sqlite3.Connection) -> None:
    seed(factory, "t-1", "gone-1")
    released(factory, "gone-1", "unclaimed")  # `tl step release --abandon`: the claim is back, no hold
    admission = Admission()
    idle = Bench(factory, ReadyTracker([bead("t-1")], ready=[]), admission).round()
    assert moves(idle) == [] and admission.requests == []  # no approval label on it: nothing starts, nothing is skipped
    found = Bench(factory, ReadyTracker([bead("t-1")], ready=["t-1"]), admission).round()
    assert moves(found) == [("t-1", "start", "started")] and admission.requests == ["t-1"]


def test_skips_abandoned_attempted_assigned_and_ancestry_and_a_second_round_admits_nothing_new(factory: sqlite3.Connection) -> None:
    seed(factory, "t-1", "gone-1")
    released(factory, "gone-1", "unclaimed")
    held(factory, "gone-1")
    seed(factory, "t-2", "lapsed", entry=ENTRY)
    ready = ReadyTracker(
        [bead("t-1", 0), bead("t-2", 0), bead("t-3", 0, assignee="person"), bead("t-4", 0, parent="missing"), bead("t-5", 4)],
        ready=["t-1", "t-2", "t-3", "t-4", "t-5"],
    )
    admission = Admission(effect=lambda task: seed(factory, task, f"a-{task}", entry=ENTRY))
    bench = Bench(factory, ready, admission)
    bench.seen = "matching"
    first = bench.round()
    assert moves(first) == [("t-2", "report", "running"), ("t-1", "skip", "abandoned"), ("t-2", "skip", "attempted"),
                            ("t-3", "skip", "assigned"), ("t-4", "skip", "ancestry"), ("t-5", "start", "started")]
    skips = {(each.task_id, each.word): each.attempt_id for each in first.moves if each.action == "skip"}
    assert (skips[("t-1", "abandoned")], skips[("t-2", "attempted")], skips[("t-3", "assigned")]) == ("gone-1", "lapsed", "")
    assert any(line.endswith(" tasks t-1 plan skip abandoned gone-1") for line in bench.lines)
    second = bench.round()
    assert ("t-5", "skip", "attempted") in moves(second) and ("t-5", "report", "running") in moves(second)
    assert admission.requests == ["t-5"] and ready.reads == ["missing", "missing"]  # one show per unique parent per round


def test_the_round_log_holds_fixed_words_one_line_per_move_and_a_closing_line(factory: sqlite3.Connection) -> None:
    ready = ReadyTracker([bead("t-1"), bead("t 2\nforged line")], ready=["t-1", "t 2\nforged line"])
    admission = Admission({"t-1": AdmitRefused("claimed_elsewhere", detail="/home/person/.secret")},
                          effect=lambda task: seed(factory, task, f"a-{task}"))
    bench = Bench(factory, ready, admission)
    found = bench.round()
    assert len(bench.lines) == len(found.moves) + 1 == 3
    assert all(LINE.fullmatch(line) for line in bench.lines), bench.lines
    # a forged id: one word, never a line; the started attempt's step
    assert bench.lines[0].split(" ")[2:] == ["invalid", "plan", "start", "started", "invalid"]
    assert not any("secret" in line or "\n" in line for line in bench.lines)


def test_a_log_that_cannot_be_written_changes_nothing_but_logged(factory: sqlite3.Connection) -> None:
    def broken(_line: str) -> None:
        raise PermissionError("rounds.log")

    seed(factory, "tl-1", "attempt")
    ready = ReadyTracker([bead("t-1")], ready=["t-1"])
    logging, failing = Bench(factory, ready), Bench(factory, ready)
    failing.log = broken
    found = failing.round()
    assert found.logged is False and exit_code(found) == 0
    assert found.moves == logging.round().moves


def test_an_attempt_abandoned_after_the_snapshot_is_skipped_never_admitted_afresh(factory: sqlite3.Connection) -> None:
    seed(factory, "tl-1", "attempt", entry=ENTRY)
    bench = Bench(factory, ReadyTracker())
    bench.during = lambda: released(factory, "attempt", "unclaimed")  # a person's `tl step release --abandon`, racing
    found = bench.round()
    assert found.moves == (Move("tl-1", "skip", "abandoned", "attempt", step="plan"),) and exit_code(found) == 0
    assert bench.admission.requests == bench.launcher.calls == []
    bench.during = lambda: None
    assert bench.round().moves == ()  # the next snapshot sees the abandon: nothing


@pytest.mark.parametrize("refusal", [LaunchRefused("registration_conflict"), LaunchRefused("registration_refused")],
                         ids=lambda refusal: refusal.reason)
def test_a_candidate_another_start_admitted_meanwhile_is_a_per_task_refusal(
    factory: sqlite3.Connection, refusal: LaunchRefused
) -> None:
    """Between the round's snapshot and its admission another start admits t-2: start launches that existing attempt, whose
    launcher refusal is about t-2 alone; the round goes on to t-3 and exits 0."""
    seed(factory, "tl-0", "running", entry=ENTRY)
    ready = ReadyTracker([bead("t-2", 0), bead("t-3", 1)], ready=["t-2", "t-3"])
    bench = Bench(factory, ready)
    bench.seen, bench.during = "matching", lambda: seed(factory, "t-2", "other", entry=ENTRY)  # one snapshot read: once
    bench.launcher.results["t-2"] = refusal
    found = bench.round()
    assert moves(found)[1:] == [("t-2", "start", f"refused:{refusal.reason}"), ("t-3", "start", "started")]
    assert bench.admission.requests == ["t-3"] and found.stopped == "" and exit_code(found) == 0


LEAK = leaked_claim("t-1")


@pytest.mark.parametrize("admit, launch, expected, stopped, code", [
    (AdmitUnavailable("tracker", claim_leaked=True, detail="bd"), None,
     [("t-1", "start", "unavailable:tracker"), ("t-1", "report", "claim_leaked")], "unavailable:tracker", 3),
    (AdmitRefused("no_free_slot", claim_leaked=True), None, [("t-1", "report", "claim_leaked")], "no_free_slot", 0),
    (AdmitRefused("claimed_elsewhere", claim_leaked=True), None,
     [("t-1", "start", "refused:claimed_elsewhere"), ("t-1", "report", "claim_leaked"), ("t-2", "start", "started")], "", 0),
    (AdmitRefused("checkout"), None, [("t-1", "start", "refused:checkout")], "refused:checkout", 1),
    (AdmitRefused("task"), None, [("t-1", "start", "refused:task")], "refused:task", 1),
    (AdmitRefused("input"), None, [("t-1", "start", "refused:input")], "refused:input", 1),
    (None, LaunchUncertain(KEY, ENTRY), [("t-1", "start", "uncertain:launch")], "uncertain:launch", 3),
    (None, LaunchUnavailable("start"), [("t-1", "start", "unavailable:start")], "unavailable:start", 3),
    (None, LaunchRefused("registration_refused"),
     [("t-1", "start", "refused:registration_refused"), ("t-2", "start", "started")], "", 0),
])
def test_admission_stops_on_unknowns_and_its_own_inputs_and_reports_every_leaked_claim(
    factory: sqlite3.Connection, admit: AdmitResult | None, launch: LaunchResult | None,
    expected: list[tuple[str, str, str]], stopped: str, code: int,
) -> None:
    ready = ReadyTracker([bead("t-1", 0), bead("t-2", 1)], ready=["t-1", "t-2"])
    bench = Bench(factory, ready, Admission({} if admit is None else {"t-1": admit}))
    if launch is not None:
        bench.launcher.results["t-1"] = launch  # a fresh admission whose launch failed: the attempt stays admitted
    found = bench.round()
    assert (moves(found), found.stopped, exit_code(found)) == (expected, stopped, code)
    leaked = [each for each in found.moves if each.word == "claim_leaked"]
    assert all(each.detail == LEAK for each in leaked)
    assert sum(line.endswith(" tasks t-1 report claim_leaked") for line in bench.lines) == len(leaked)
    assert bench.admission.requests == (["t-1", "t-2"] if ("t-2", "start", "started") in expected else ["t-1"])


def test_with_every_adopted_slot_reserved_admission_reads_no_tracker(factory: sqlite3.Connection) -> None:
    factory.execute("INSERT INTO slot (repo_id,name,path) VALUES ('repo','s1','/slots/s1')")
    factory.execute("INSERT INTO reservation VALUES ('s1','repo',1,'attempt')")
    seed(factory, "tl-1", "attempt", entry=ENTRY)
    ready = ReadyTracker([bead("t-1")], ready=["t-1"], ready_fault=BdError("timeout", "never read"))
    bench = Bench(factory, ready, free=False)
    bench.seen = "matching"
    found = bench.round()
    assert moves(found) == [("tl-1", "report", "running")] and found.stopped == "no_free_slot" and exit_code(found) == 0
    assert ready.ready_reads == [] and ready.reads == [] and bench.admission.requests == []
    opened = Bench(factory, ready)  # one more adopted slot without a reservation row: the ready read runs
    opened.seen = "matching"
    assert opened.round().stopped == "unavailable:tracker" and ready.ready_reads == ["auto"]


def test_a_move_identical_to_the_previous_rounds_is_not_written_again(factory: sqlite3.Connection) -> None:
    seed(factory, "tl-1", "attempt", entry=ENTRY)
    bench = Bench(factory)
    first = bench.round(replace(REQUEST, quiet=frozenset()))
    assert [line.split(" ")[2:] for line in bench.lines] == [["tl-1", "plan", "relaunch", "relaunched", "attempt"], ["round", "moves=1"]]
    second = bench.round(replace(REQUEST, quiet=first.written))
    assert second.moves == first.moves and len(bench.lines) == 2  # still in the result, not in the log
    bench.now = 200
    third = bench.round(replace(REQUEST, quiet=second.written))
    assert [line.split(" ")[2:] for line in bench.lines[2:]] == [["tl-1", "plan", "report", "stuck:expired_admitted", "attempt"],
                                                                ["round", "moves=1"]]
    bench.round(replace(REQUEST, quiet=third.written))
    assert len(bench.lines) == 4


def test_the_closing_line_is_written_when_the_stopped_word_changes(factory: sqlite3.Connection) -> None:
    bench = Bench(factory)
    idle = bench.round(replace(REQUEST, quiet=frozenset()))
    assert idle.moves == () and bench.lines[-1].endswith(" tasks round moves=0")
    bench.round(replace(REQUEST, quiet=idle.written))
    assert len(bench.lines) == 1  # an idle round writes nothing
    bench.ready = ReadyTracker(ready_fault=BdError("timeout", "bd failed"))
    bench.round(replace(REQUEST, quiet=idle.written))
    assert len(bench.lines) == 2 and bench.lines[-1].endswith(" tasks round moves=0 stopped=unavailable:tracker")


def test_an_admission_skip_stays_quiet_across_rounds_with_no_free_slot(factory: sqlite3.Connection) -> None:
    """A round with every slot held never reads the ready rows: the previous round's `skip abandoned` stands unchanged, so
    the next round with a free slot does not write it again."""
    seed(factory, "t-1", "gone-1")
    released(factory, "gone-1", "unclaimed")
    held(factory, "gone-1")
    bench = Bench(factory, ReadyTracker([bead("t-1")], ready=["t-1"]))
    found = bench.round(replace(REQUEST, quiet=frozenset()))
    factory.execute("DELETE FROM slot WHERE repo_id='other'")
    found = bench.round(replace(REQUEST, quiet=found.written))
    assert found.stopped == "no_free_slot" and found.moves == ()
    factory.execute("INSERT INTO slot (repo_id,name,path) VALUES ('other','s1','/other/s1')")
    found = bench.round(replace(REQUEST, quiet=found.written))
    assert moves(found) == [("t-1", "skip", "abandoned")]
    assert sum(line.endswith(" tasks t-1 plan skip abandoned gone-1") for line in bench.lines) == 1


def test_after_a_failed_log_write_the_next_round_writes_the_state_again(factory: sqlite3.Connection) -> None:
    seed(factory, "tl-1", "attempt", entry=ENTRY)
    bench = Bench(factory)

    def broken(_line: str) -> None:
        raise PermissionError("rounds.log")

    bench.log = broken
    failed = bench.round(replace(REQUEST, quiet=frozenset()))
    assert failed.logged is False and failed.written == frozenset()
    bench.log = bench.lines.append
    again = bench.round(replace(REQUEST, quiet=failed.written))
    assert [line.split(" ")[2:] for line in bench.lines] == [["tl-1", "plan", "relaunch", "relaunched", "attempt"], ["round", "moves=1"]]
    bench.round(replace(REQUEST, quiet=again.written))
    assert len(bench.lines) == 2  # once written, identical rounds stay silent


def test_a_verified_plan_whose_entry_still_runs_is_left_to_that_entry(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    verified_released(registered, tmp_path, slot, checkouts, slot_files)
    bench = Bench(registered)
    bench.seen = "matching"  # the entry publishes right after its release
    assert bench.round().moves == () and bench.recorded.calls == []
    bench.seen = "gone"
    assert bench.round().moves == (Move("tl-1", "publish", "published", "attempt", step="plan"),) and bench.recorded.calls == ["publish"]


def test_a_stop_after_the_first_settle_move_performs_no_further_move(factory: sqlite3.Connection) -> None:
    seed(factory, "tl-1", "first")
    seed(factory, "tl-2", "second")
    ready = ReadyTracker([bead("t-1")], ready=["t-1"])
    bench = Bench(factory, ready)
    bench.stopping = lambda: len(bench.launcher.calls) >= 1
    found = bench.round()
    assert moves(found) == [("tl-1", "relaunch", "relaunched")] and found.stopped == "interrupted" and exit_code(found) == 0
    assert bench.launcher.calls == ["tl-1"] and ready.ready_reads == [] and bench.admission.requests == []
    assert bench.lines[-1].endswith(" tasks round moves=1 stopped=interrupted")


def test_a_stop_asked_during_the_last_move_still_closes_the_round_interrupted(factory: sqlite3.Connection) -> None:
    bench = Bench(factory, ReadyTracker([bead("t-1")], ready=["t-1"]))
    bench.stopping = lambda: len(bench.admission.requests) >= 1  # pressed while t-1 starts; no move is left after it
    found = bench.round()
    assert moves(found) == [("t-1", "start", "started")] and found.stopped == "interrupted"
    assert bench.lines[-1].endswith(" tasks round moves=1 stopped=interrupted")


def test_a_stop_between_two_candidates_never_claims_the_second(factory: sqlite3.Connection) -> None:
    ready = ReadyTracker([bead("t-1", 0), bead("t-2", 1)], ready=["t-1", "t-2"])
    bench = Bench(factory, ready)
    bench.stopping = lambda: len(bench.admission.requests) >= 1
    found = bench.round()
    assert moves(found) == [("t-1", "start", "started")] and found.stopped == "interrupted"
    assert bench.admission.requests == ["t-1"]


def test_a_skip_repeated_every_round_is_a_move_so_moves_0_closes_only_once_the_skips_stop(factory: sqlite3.Connection) -> None:
    """M3 finding 6: an abandoned ready task is skipped by every round, quietly after the first, so the unchanged closing
    line `round moves=1` is quiet too; the first round without the skip writes `round moves=0`."""
    seed(factory, "t-1", "gone-1")
    released(factory, "gone-1", "unclaimed")
    held(factory, "gone-1")
    bench = Bench(factory, ReadyTracker([bead("t-1")], ready=["t-1"]))
    found = bench.round(replace(REQUEST, quiet=frozenset()))
    assert [line.split(" ")[2:] for line in bench.lines] == [["t-1", "plan", "skip", "abandoned", "gone-1"], ["round", "moves=1"]]
    found = bench.round(replace(REQUEST, quiet=found.written))
    assert moves(found) == [("t-1", "skip", "abandoned")] and len(bench.lines) == 2
    bench.ready = ReadyTracker()
    bench.round(replace(REQUEST, quiet=found.written))
    assert len(bench.lines) == 3 and bench.lines[-1].endswith(" tasks round moves=0")


def test_a_slot_no_attempt_holds_but_nothing_can_use_is_named_in_the_log_not_called_held(factory: sqlite3.Connection) -> None:
    """`no_free_slot` with a missing slot: one `unusable:<slot>:<why>` line for the task that could not start, quiet while
    unchanged."""
    ready = ReadyTracker([bead("t-1")], ready=["t-1"])
    gone = SlotView("s4", Path("/slots/s4"), "unknown", "not_listed")
    bench = Bench(factory, ready, Admission({"t-1": AdmitRefused("no_free_slot", (gone,))}))
    first = bench.round()
    assert moves(first) == [("t-1", "report", "unusable:s4:not_listed")] and first.stopped == "no_free_slot"
    assert first.moves[0].detail == "/slots/s4" and any(line.endswith(" tasks t-1 report unusable:s4:not_listed") for line in bench.lines)
    lines = len(bench.lines)
    bench.round(replace(REQUEST, quiet=first.written))
    assert len(bench.lines) == lines


def test_an_advance_with_every_free_slot_unusable_names_it_and_the_next_renders_its_path(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    store = verified_released(registered, tmp_path, slot, checkouts, slot_files)
    assert isinstance(BranchPublish(store, checkouts, slot_files, lambda: 40, ids=NativeIds()).publish(KEY), BranchPublished)
    gone = SlotView("s4", Path("/slots/s4"), "unknown", "not_listed")
    bench = Bench(registered, ReadyTracker())
    bench.advance = Advances(AdmitRefused("no_free_slot", (gone,)))
    found = bench.round()
    assert ("tl-1", "report", "unusable:s4:not_listed") in moves(found) and found.stopped == "no_free_slot"
    lines = human("next", found, None)
    assert any(line.strip() == "/slots/s4" for line in lines) and any(line.startswith("unusable:s4:not_listed: ") for line in lines)


def test_a_transient_slot_state_is_not_called_unusable(factory: sqlite3.Connection) -> None:
    ready = ReadyTracker([bead("t-1")], ready=["t-1"])
    busy = SlotView("s1", Path("/slots/s1"), "unknown", "locked")
    found = Bench(factory, ready, Admission({"t-1": AdmitRefused("no_free_slot", (busy,))})).round()
    assert moves(found) == [] and found.stopped == "no_free_slot"


def test_after_a_discard_a_round_told_to_retake_admits_a_lapsed_claim_with_no_attempt_and_otherwise_never(
    factory: sqlite3.Connection,
) -> None:
    lapsed = Bead("t-1", status="in_progress", assignee="taskloop", labels=("auto",), lease_expires_at="1970-01-01T00:00:05Z")
    for retake, admitted in ((False, []), (True, ["t-1"])):
        bench = Bench(factory, ReadyTracker([lapsed]))
        found = bench.round(replace(REQUEST, retake=retake))
        assert bench.admission.requests == admitted and found.stopped == ""
