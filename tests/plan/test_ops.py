"""The plan commands' operations over a real factory.db file (read-only where the command is) with recording admission,
launcher and verifier fakes and a fake entry observation: no process is started or inspected."""

import json
import sqlite3
from collections.abc import Callable, Generator
from dataclasses import replace
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from git_porcelain import GitUnavailable, NotARepo, Repo
from git_porcelain.testing import FakeWorktree
from sqlite_store import Store

from taskloop.cli_composition import adopt, open_plan_reads, open_plan_start, open_plan_verify
from taskloop.plan import SANDBOX, PlanAttempts
from taskloop.plan_admit import AdmitRefused, AdmitRequest, AdmitResult, Admitted, AdmitUnavailable
from taskloop.plan_files import PlanFiles
from taskloop.plan_launch import AlreadyRunning, Entry, Launched, LaunchRefused, LaunchResult, LaunchUnavailable, LaunchUncertain
from taskloop.plan_ops import (
    MAX_MINUTES,
    UNCLAIMING,
    Adoption,
    AttemptStatus,
    Checked,
    Ended,
    EntryState,
    Failed,
    Listed,
    Move,
    Next,
    PublishedTask,
    Reads,
    Round,
    Shown,
    Started,
    Starting,
    StartRequest,
    attempts_status,
    exit_code,
    last_entry,
    next_step,
    publish_task,
    start,
    status,
    verify_task,
)
from taskloop.plan_publish import BranchPublished, NotPublished, PlanPublish, PublishResult
from taskloop.plan_reads import PublishedRow
from taskloop.plan_release import NotReleased, PlanRelease, Released, ReleaseResult
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore
from taskloop.plan_types import (
    AttemptKey,
    AttemptResult,
    Checkouts,
    NotApplicable,
    Rejected,
    Seen,
    SlotFiles,
    Unsettled,
    Verified,
    VerifyRefused,
    VerifyResult,
    VerifyUnavailable,
)
from taskloop.plan_verifier import PlanVerifier
from taskloop.slot_lock import custody, hold
from taskloop.slots import Adopted, SlotView

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
REQUEST = StartRequest("tl-1", "tasks", "/tracker", Path("/checkout"), "model-m", "effort-e", 30)


class Admission:
    def __init__(self, result: AdmitResult, effect: Callable[[], object] = lambda: None) -> None:
        self.result, self.effect = result, effect
        self.requests: list[AdmitRequest] = []

    def admit(self, request: AdmitRequest) -> AdmitResult:
        self.requests.append(request)
        self.effect()
        return self.result


class Launcher:
    def __init__(self, result: LaunchResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []
        self.minutes: list[int] = []

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        self.calls.append((backlog, task_id))
        self.minutes.append(minutes)
        return self.result


class Repeats:
    """The repeat port: records each call; `start` reaches it only for a captured current attempt."""

    def __init__(self, result: Started | Failed | None = None) -> None:
        self.result = result
        self.calls: list[tuple[str, str, AttemptKey, Entry | None, int]] = []

    def repeat(self, backlog: str, task_id: str, current: AttemptKey, entry: Entry | None, minutes: int) -> Started | Failed:
        self.calls.append((backlog, task_id, current, entry, minutes))
        assert self.result is not None, "only a captured attempt repeats"
        return self.result


PARKED = Released("s1", "d" * 40, True, "kept", False)


class Releases:
    """The release port: records each call."""

    def __init__(self, result: ReleaseResult = PARKED) -> None:
        self.result, self.calls = result, list[tuple[AttemptKey, bool]]()

    def release(self, key: AttemptKey, abandon: bool, me: Entry | None = None) -> ReleaseResult:
        self.calls.append((key, abandon))
        return self.result


PUSHED = BranchPublished("x" * 40, "x" * 40)


class Publishes:
    """The publish port: records each call."""

    def __init__(self, result: PublishResult = PUSHED) -> None:
        self.result, self.keys = result, list[AttemptKey]()

    def publish(self, key: AttemptKey) -> PublishResult:
        self.keys.append(key)
        return self.result


def releaser(store: PlanStore, checkouts: Checkouts, slot_files: SlotFiles) -> PlanRelease:
    """The real release over the fakes: the entry gone, the agent gone, the real slot lock, a claim that returns."""
    return PlanRelease(store, checkouts, slot_files, lambda _entry: "gone", gone, custody, lambda _root, _task: True, lambda: 30)


class Verifier:
    def __init__(self, result: VerifyResult) -> None:
        self.result = result
        self.keys: list[AttemptKey] = []

    def verify(self, key: AttemptKey) -> VerifyResult:
        self.keys.append(key)
        return self.result


@pytest.fixture
def reader(admitted: Path) -> Generator[PlanStore]:
    con = Store(SCHEMA).open_ro(admitted)
    assert con is not None
    yield PlanStore(lambda: con)
    con.close()


@pytest.fixture
def empty(tmp_path: Path) -> Generator[PlanStore]:
    con = Store(SCHEMA).open_rw(tmp_path / "empty.db")
    assert con is not None
    yield PlanStore(lambda: con)
    con.close()


def write(path: Path, sql: str, *values: object) -> None:
    con = sqlite3.connect(path, isolation_level=None)
    con.execute(sql, values)
    con.close()


def test_a_first_start_admits_with_the_fixed_sandbox_and_launches(empty: PlanStore) -> None:
    admission, launcher = Admission(Admitted(KEY, "s1")), Launcher(Launched(KEY, ENTRY))
    started = start(Starting(empty, admission, launcher, lambda: 1000, Repeats()), REQUEST)
    assert started == Started("started", "tasks", "tl-1", "attempt", False, ENTRY)
    request = admission.requests[0]
    assert (request.task_id, request.backlog, request.tracker_root, request.checkout) == ("tl-1", "tasks", "/tracker", Path("/checkout"))
    assert (request.model, request.effort, request.sandbox, request.deadline) == ("model-m", "effort-e", SANDBOX, 1000 + 30 * 60)
    assert (launcher.calls, launcher.minutes) == ([("tasks", "tl-1")], [30])


@pytest.mark.parametrize("minutes", [0, -5, MAX_MINUTES + 1, 10**400])
def test_minutes_out_of_range_are_refused_before_any_read_or_launch(minutes: int) -> None:
    admission, launcher = Admission(Admitted(KEY, "s1")), Launcher(Launched(KEY, ENTRY))
    unread = PlanStore(lambda: None)  # any read would raise StoreUnavailable
    found = start(Starting(unread, admission, launcher, lambda: 1000, Repeats()), replace(REQUEST, minutes=minutes))
    assert found == Failed("refused", "choices", f"--minutes must be from 1 to {MAX_MINUTES}")
    assert admission.requests == [] and launcher.calls == []


def test_a_launch_failure_after_a_fresh_admission_says_the_attempt_is_admitted(empty: PlanStore, reader: PlanStore) -> None:
    fresh = start(Starting(empty, Admission(Admitted(KEY, "s1")), Launcher(LaunchUnavailable("start")), lambda: 10, Repeats()), REQUEST)
    assert fresh == Failed("unavailable", "start", admitted=True)
    failing = Launcher(LaunchUnavailable("start"))
    existing = start(Starting(reader, Admission(AdmitRefused("task")), failing, lambda: 10, Repeats()), REQUEST)
    assert existing == Failed("unavailable", "start")


@pytest.mark.parametrize("launched, expected", [
    (Launched(KEY, ENTRY), Started("relaunched", "tasks", "tl-1", "attempt", True, ENTRY)),
    (AlreadyRunning(KEY, ENTRY), Started("already_running", "tasks", "tl-1", "attempt", True, ENTRY)),
    (LaunchRefused("dispatched"), Started("already_dispatched", "tasks", "tl-1", "attempt", True)),
    (LaunchRefused("registration_refused"), Failed("refused", "registration_refused")),
    (LaunchUnavailable("store"), Failed("unavailable", "store")),
    (LaunchUncertain(KEY, ENTRY), Failed("uncertain", "launch", "The registered entry may run; `tl plan show` observes it")),
])
def test_an_existing_attempt_is_launched_as_admitted_without_the_tracker(
    reader: PlanStore, launched: LaunchResult, expected: Started | Failed
) -> None:
    admission, launcher = Admission(AdmitRefused("task")), Launcher(launched)
    assert start(Starting(reader, admission, launcher, lambda: 10, Repeats()), REQUEST) == expected
    assert admission.requests == []  # the given model, effort and minutes are not applied
    assert launcher.calls == [("tasks", "tl-1")]


def test_a_concurrent_start_that_won_is_launched_as_existing(admitted: Path, reader: PlanStore) -> None:
    write(admitted, "UPDATE plan_attempt SET task_id='hidden'")
    admission = Admission(AdmitRefused("task_attempted"), lambda: write(admitted, "UPDATE plan_attempt SET task_id='tl-1'"))
    launched = start(Starting(reader, admission, Launcher(AlreadyRunning(KEY, ENTRY)), lambda: 10, Repeats()), REQUEST)
    assert launched == Started("already_running", "tasks", "tl-1", "attempt", True, ENTRY)
    assert len(admission.requests) == 1


VIEW = SlotView("s1", Path("/slots/s1"), "held", attempt_id="other")


@pytest.mark.parametrize("admit, expected", [
    (AdmitRefused("no_free_slot", (VIEW,)), Failed("refused", "no_free_slot", slots=(VIEW,))),
    (AdmitRefused("claimed_elsewhere"), Failed("refused", "claimed_elsewhere")),
    (AdmitRefused("constraint", claim_leaked=True, detail="x"), Failed("refused", "constraint", "x", claim_leaked=True)),
    (AdmitUnavailable("tracker", claim_leaked=True, detail="bd"), Failed("unavailable", "tracker", "bd", claim_leaked=True)),
    (AdmitUnavailable("store"), Failed("unavailable", "store")),
])
def test_a_refusal_or_unknown_stops_before_any_launch(empty: PlanStore, admit: AdmitResult, expected: Failed) -> None:
    launcher = Launcher(Launched(KEY, ENTRY))
    assert start(Starting(empty, Admission(admit), launcher, lambda: 10, Repeats()), REQUEST) == expected
    assert launcher.calls == []


NEXT: list[tuple[str, EntryState, AttemptResult, bool, Next]] = [
    ("admitted", "none", AttemptResult("pending", "admitted"), False, "start"),
    ("admitted", "gone", AttemptResult("pending", "admitted"), False, "start"),
    ("admitted", "different_process", AttemptResult("pending", "admitted"), False, "start"),
    ("admitted", "none", AttemptResult("pending", "admitted"), True, "stuck:expired_admitted"),
    ("admitted", "running", AttemptResult("pending", "admitted"), False, "wait"),
    ("registered", "running", AttemptResult("pending", "registered"), False, "wait"),
    ("registered", "running", AttemptResult("pending", "registered"), True, "stuck:hung"),
    ("dispatching", "gone", AttemptResult("pending", "dispatching"), False, "stuck:entry_lost"),
    ("registered", "different_process", AttemptResult("pending", "registered"), True, "stuck:entry_lost"),
    ("captured", "gone", AttemptResult("pending", "verification"), True, "verify"),
    ("captured", "gone", AttemptResult("pending", "session_pending"), False, "stuck:unpublished"),
    ("captured", "gone", AttemptResult("pending", "validation_pending"), False, "stuck:unpublished"),
    ("captured", "gone", AttemptResult("conflict", "session"), False, "stuck:conflict"),
    ("registered", "gone", AttemptResult("conflict", "session"), False, "stuck:conflict"),
    ("captured", "gone", AttemptResult("collected", "verified"), True, "done"),
    ("captured", "running", AttemptResult("collected", "rejected:paths"), False, "done"),
    ("admitted", "unknown", AttemptResult("pending", "admitted"), False, "unknown"),
    ("captured", "gone", AttemptResult("unavailable", "collect"), False, "unknown"),
    ("captured", "gone", AttemptResult("refused", "absent"), False, "unknown"),
]


@pytest.mark.parametrize("phase, entry, collected, passed, expected", NEXT)
def test_the_next_step_table(phase: str, entry: EntryState, collected: AttemptResult, passed: bool, expected: Next) -> None:
    assert next_step(phase, entry, collected, passed) == expected


@pytest.mark.parametrize("phase, expected", [
    ("admitted", "start"), ("dispatching", "stuck:entry_lost"), ("registered", "stuck:entry_lost"),
])
def test_an_entry_from_another_boot_is_relaunched_past_the_deadline_only_while_admitted(phase: str, expected: Next) -> None:
    pending = AttemptResult("pending", phase)
    assert next_step(phase, "different_process", pending, True, rebooted=True) == expected


def gone(_worker: Worker) -> bool:
    return True


def nothing_left(_key: AttemptKey) -> Unsettled | None:
    return None


def observe(seen: Seen, calls: list[tuple[int, str, str]]) -> Callable[[tuple[int, str, str]], Seen]:
    def observed(entry: tuple[int, str, str]) -> Seen:
        calls.append(entry)
        return seen

    return observed


@pytest.mark.parametrize("seen, now, entry, expected", [
    ("matching", 10, "running", "wait"),
    ("matching", 200, "running", "stuck:hung"),
    ("gone", 10, "gone", "start"),
    ("different_process", 10, "different_process", "start"),
    ("unknown", 10, "unknown", "unknown"),
    ("gone", 200, "gone", "stuck:expired_admitted"),
])
def test_show_observes_the_registered_entry(
    admitted: Path, reader: PlanStore, tmp_path: Path, seen: Seen, now: float, entry: EntryState, expected: Next
) -> None:
    write(admitted, "UPDATE plan_attempt SET entry_pid=?,entry_start=?,entry_boot=?", *ENTRY)
    calls: list[tuple[int, str, str]] = []
    shown = status(Reads(reader, observe(seen, calls), lambda: now, nothing_left, lambda: "boot"), tmp_path / "art", "tasks", "tl-1")
    assert isinstance(shown, Shown)
    assert (shown.status.entry, shown.status.next, shown.status.deadline_passed) == (entry, expected, now >= 100)
    assert calls == [ENTRY]
    assert (shown.status.entry_process, shown.status.worker) == (ENTRY, None)
    write(admitted, "UPDATE plan_attempt SET phase='dispatching',base_commit=?,worker_pid=42,worker_pgid=41", "a" * 40)
    again = status(Reads(reader, observe(seen, calls), lambda: now, nothing_left, lambda: "boot"), tmp_path / "art", "tasks", "tl-1")
    assert isinstance(again, Shown) and again.status.worker == (42, 41)


@pytest.mark.parametrize("boot, expected", [("new-boot", "start"), ("boot", "stuck:expired_admitted"), (None, "stuck:expired_admitted")])
def test_an_expired_admitted_attempt_registered_before_a_reboot_shows_start(
    admitted: Path, reader: PlanStore, tmp_path: Path, boot: str | None, expected: Next
) -> None:
    """The entry stored `boot`; this machine's boot id differs only after a reboot (unknown never counts as one)."""
    write(admitted, "UPDATE plan_attempt SET entry_pid=?,entry_start=?,entry_boot=?", *ENTRY)
    reads = Reads(reader, observe("different_process", []), lambda: 200, nothing_left, lambda: boot)
    shown = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(shown, Shown) and (shown.status.deadline_passed, shown.status.next) == (True, expected)


def test_show_creates_nothing_and_computes_the_attempt_directory(admitted: Path, reader: PlanStore, tmp_path: Path) -> None:
    def files() -> list[str]:  # SQLite's own -wal/-shm side files aside
        return sorted(path.name for path in tmp_path.iterdir() if not path.name.startswith("factory.db-"))

    def rows() -> list[tuple[object, ...]]:
        con = sqlite3.connect(admitted)
        try:
            return con.execute("SELECT * FROM plan_attempt").fetchall()
        finally:
            con.close()

    before, stored = files(), rows()
    shown = status(Reads(reader, observe("gone", []), lambda: 10, nothing_left, lambda: "boot"), tmp_path / "art", "tasks", "tl-1")
    assert isinstance(shown, Shown)
    directory = PlanFiles(tmp_path / "art").root / PlanFiles(tmp_path / "art").directory(KEY)
    assert (shown.directory, shown.entry_log) == (directory, directory / "entry.log")
    assert (shown.status.entry, shown.status.next, shown.status.result) == ("none", "start", AttemptResult("pending", "admitted"))
    assert (files(), rows()) == (before, stored)
    assert not (tmp_path / "art").exists()
    reads = Reads(reader, observe("gone", []), lambda: 10, nothing_left, lambda: "boot")
    assert status(reads, tmp_path / "art", "tasks", "tl-2") == Failed("refused", "absent", "No attempt for tl-2 in backlog tasks")


@pytest.mark.parametrize("now, stuck, rows", [(10, False, 1), (10, True, 0), (200, True, 1)])
def test_list_keeps_only_stuck_or_unknown_when_asked(reader: PlanStore, now: float, stuck: bool, rows: int) -> None:
    listed = attempts_status(Reads(reader, observe("gone", []), lambda: now, nothing_left, lambda: "boot"), stuck=stuck)
    assert isinstance(listed, Listed) and len(listed.attempts) == rows


@pytest.mark.parametrize("verdict, expected", [
    (Verified("blob"), Checked("verified", "tasks", "tl-1", "attempt", "released", "published")),
    (Verified("blob", reused=True), Checked("reused", "tasks", "tl-1", "attempt", "released", "published")),
    (Rejected("paths"), Failed("rejected", "paths", "Release: released")),
    (NotApplicable("incomplete"), Failed("not_applicable", "incomplete")),
    (VerifyRefused("session"), Failed("refused", "session")),
    (Unsettled("dirty"), Failed("unsettled", "dirty")),
    (VerifyUnavailable("git:NotARepo"), Failed("unavailable", "git:NotARepo")),
    (VerifyUnavailable("inconsistent"), Failed("defect", "inconsistent")),
])
def test_verify_maps_every_verdict(reader: PlanStore, verdict: VerifyResult, expected: Checked | Failed) -> None:
    verifier, releases, publishes = Verifier(verdict), Releases(), Publishes()
    assert verify_task(reader, verifier, releases, publishes, "tasks", "tl-1") == expected
    assert verifier.keys == [KEY]
    assert releases.calls == ([(KEY, False)] if isinstance(verdict, (Verified, Rejected)) else [])  # only after a verdict, settled
    assert publishes.keys == ([KEY] if isinstance(verdict, Verified) else [])  # only a verified plan, after its release
    absent = Verifier(verdict)
    missing = Failed("refused", "absent", "No attempt for tl-9 in backlog tasks")
    assert verify_task(reader, absent, releases, publishes, "tasks", "tl-9") == missing
    assert absent.keys == []


def test_verify_returns_a_stored_verdict_with_no_git_read(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    path = "docs/design/tl-1/plan.md"

    def agent(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        slot.write_file(path, "# Plan\n")
        text = json.dumps({"disposition": "planned", "plan_path": path, "paths": [path], "message": "Plan", "explanation": "done"})
        worker = Worker(pid=42, pgid=42, start="native-start", boot="boot")
        return FakeRun(RunOutcome(rc=0, worker=worker, summary=Summary(text=text, rc=0, stands=True)))(harness, spec, timeout, hooks)

    store = PlanStore(lambda: registered)
    attempts = PlanAttempts(store, PlanFiles(tmp_path), lambda: ("/bin/codex", {}), agent, lambda: 10, checkouts, slot_files)
    assert attempts.execute(KEY, ENTRY).reason == "verification"
    releasing, publishing = releaser(store, checkouts, slot_files), PlanPublish(store, checkouts, slot_files, lambda: 40)
    first = verify_task(store, PlanVerifier(store, checkouts, slot_files, gone, lambda: 20, hold), releasing, publishing, "tasks", "tl-1")
    assert first == Checked("verified", "tasks", "tl-1", "attempt", "released", "published") and slot.branch() is None
    slot.repo.drop_checkout(slot.path)
    opened: list[Path] = []

    def counted(where: Path) -> Repo:
        opened.append(where)
        return checkouts(where)

    again = releaser(store, counted, slot_files)  # already released and published: nothing pending, no Git
    verifier = PlanVerifier(store, counted, slot_files, gone, lambda: 20, hold)
    assert verify_task(store, verifier, again, PlanPublish(store, counted, slot_files, lambda: 50), "tasks", "tl-1") == first
    assert opened == []


def test_show_reads_leftovers_fresh_and_names_the_repeat(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    path, stray = "docs/design/tl-1/plan.md", "docs/design/tl-1/stray.md"

    def agent(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        slot.write_file(path, "# Plan\n")
        slot.write_file(stray, "x")
        text = json.dumps({"disposition": "planned", "plan_path": path, "paths": [path], "message": "Plan", "explanation": "done"})
        worker = Worker(pid=42, pgid=42, start="native-start", boot="boot")
        return FakeRun(RunOutcome(rc=0, worker=worker, summary=Summary(text=text, rc=0, stands=True)))(harness, spec, timeout, hooks)

    store = PlanStore(lambda: registered)
    attempts = PlanAttempts(store, PlanFiles(tmp_path), lambda: ("/bin/codex", {}), agent, lambda: 10, checkouts, slot_files)
    assert attempts.execute(KEY, ENTRY).reason == "verification"
    verifier = PlanVerifier(store, checkouts, slot_files, gone, lambda: 20, hold)
    reads = Reads(store, observe("gone", []), lambda: 10, verifier.leftovers, lambda: "boot")
    before = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(before, Shown) and (before.status.next, before.status.leftovers) == ("verify", ())  # nothing committed yet
    left = Failed("unsettled", "uncommitted", f"?? {stray}")  # as show lists it
    assert verify_task(store, verifier, Releases(), Publishes(), "tasks", "tl-1") == left
    shown = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(shown, Shown) and shown.status.next == "repeat"
    assert (shown.status.result.status, shown.status.result.reason) == ("pending", "repeat")
    assert shown.status.leftovers == ("uncommitted", f"?? {stray}")
    probed: list[AttemptKey] = []

    def counted(key: AttemptKey) -> Unsettled | None:
        probed.append(key)
        return verifier.leftovers(key)

    counting = Reads(store, observe("gone", []), lambda: 10, counted, lambda: "boot")
    assert attempts_status(counting, stuck=True) == Listed(()) and probed == []  # no Git read for a filtered-out attempt
    listed = attempts_status(counting)
    assert isinstance(listed, Listed) and [each.next for each in listed.attempts] == ["repeat"] and probed == [KEY]
    slot.remove_file(stray)
    tidied = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(tidied, Shown) and (tidied.status.next, tidied.status.leftovers) == ("verify", ())


def test_show_and_verify_agree_on_a_slot_moved_off_its_task_branch(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """Before the factory's commit, `show` reads the leftovers only on the task branch: off it, as `verify` says,
    `branch` (not repeatable), never a repeat of leftovers the commit would not reach."""
    path, near = "docs/design/tl-1/plan.md", "docs/design/tl-1/.gitignore"

    def agent(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        slot.write_file(path, "# Plan\n")
        slot.write_file(near, "x")
        text = json.dumps({"disposition": "planned", "plan_path": path, "paths": [path], "message": "Plan", "explanation": "done"})
        worker = Worker(pid=42, pgid=42, start="native-start", boot="boot")
        return FakeRun(RunOutcome(rc=0, worker=worker, summary=Summary(text=text, rc=0, stands=True)))(harness, spec, timeout, hooks)

    store = PlanStore(lambda: registered)
    attempts = PlanAttempts(store, PlanFiles(tmp_path), lambda: ("/bin/codex", {}), agent, lambda: 10, checkouts, slot_files)
    assert attempts.execute(KEY, ENTRY).reason == "verification"
    verifier = PlanVerifier(store, checkouts, slot_files, gone, lambda: 20, hold)
    reads = Reads(store, observe("gone", []), lambda: 10, verifier.leftovers, lambda: "boot")
    on = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(on, Shown) and (on.status.next, on.status.leftovers) == ("repeat", ("unsafe", near))
    slot.checkout_new("other")
    assert verifier.leftovers(KEY) == Unsettled("branch")
    off = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(off, Shown) and (off.status.next, off.status.leftovers) == ("verify", ())
    assert verify_task(store, verifier, Releases(), Publishes(), "tasks", "tl-1") == Failed("unsettled", "branch")


def test_every_opener_but_adopt_refuses_a_missing_database_and_creates_none(tmp_path: Path) -> None:
    missing = tmp_path / "factory.db"  # in an existing directory: a writable open would create it
    refused = Failed("refused", "database", "No readable factory.db at this path; `tl slot adopt` creates it")
    with open_plan_reads(missing) as reads:
        assert reads == refused
    with open_plan_start(missing, tmp_path / "art") as ports:
        assert ports == refused
    with open_plan_verify(missing) as opened:
        assert opened == refused
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6, 7, 9])
def test_another_schema_version_is_refused_schema(tmp_path: Path, version: int) -> None:
    path = tmp_path / "factory.db"
    write(path, "PRAGMA journal_mode=WAL")
    write(path, f"PRAGMA user_version={version}")
    with open_plan_reads(path) as reads:
        assert isinstance(reads, Failed) and (reads.kind, reads.reason) == ("refused", "schema")
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone() == (version,)
    con.close()


def fail(error: Exception) -> Checkouts:
    def opened(_path: Path) -> Repo:
        raise error

    return opened


@pytest.mark.parametrize("checkout, repos, kind, reason", [
    ("missing", None, "refused", "checkout"),
    (".", fail(NotARepo("not a repository")), "refused", "checkout"),
    (".", fail(GitUnavailable("git exited 128")), "unavailable", "git"),
])
def test_adopt_refuses_a_bad_checkout_before_making_anything(
    tmp_path: Path, checkout: str, repos: Checkouts | None, kind: str, reason: str
) -> None:
    database = tmp_path / "state" / "factory.db"
    found = adopt(database, tmp_path / checkout if checkout != "." else tmp_path, tmp_path / "slots", 1, repos or fail(AssertionError()))
    assert isinstance(found, Failed) and (found.kind, found.reason) == (kind, reason)
    assert not (tmp_path / "state").exists()


def test_adopt_refuses_another_schema_and_otherwise_creates_the_database(tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts) -> None:
    foreign = tmp_path / "foreign.db"
    write(foreign, "PRAGMA journal_mode=WAL")
    write(foreign, "PRAGMA user_version=9")
    refused = adopt(foreign, tmp_path, tmp_path / "slots", 1, checkouts)
    assert isinstance(refused, Failed) and (refused.kind, refused.reason) == ("refused", "schema")
    database = tmp_path / "state" / "factory.db"
    assert adopt(database, tmp_path, tmp_path / "slots", 1, checkouts) == Adoption((Adopted("s1", slot.path),))
    assert database.exists()


# the entry's longest line: a retried publication, its collected outcome, the verify, claim and release words
LONGEST = ("unavailable evidence publish=accepted then=collected:verified verify=unavailable:git claim=unrenewed release=held:slot_dirty "
           "branch=unavailable:remote")


@pytest.mark.parametrize(("tail", "expected"), [
    (None, None),
    ("", None),
    ("refused slot_staged verify=refused:not_captured\n", "refused slot_staged verify=refused:not_captured"),
    ("unavailable credentials:auth verify=refused:not_captured\nnoise\n", "unavailable credentials:auth verify=refused:not_captured"),
    ("collected verified verify=verified\nrefused \x1b]0;owned\x07\n", "collected verified verify=verified"),
    ("refused slot_staged\x9b31m\n", None),
    ("Traceback (most recent call last):\n", None),
    ("failed TypeError\n", "failed TypeError"),
    ("refused claim_lost\n", "refused claim_lost"),
    (LONGEST + "\n", LONGEST),
    (LONGEST + " x=y\n", None),
    ("refused " + "x" * 61 + "\n", None),
    ("refused a b c d e f g h\n", None),
])
def test_only_a_line_of_the_entrys_fixed_words_is_shown(tail: str | None, expected: str | None) -> None:
    assert last_entry(tail) == expected


def test_a_step_that_ended_on_a_dirty_slot_says_release_then_done_then_start_after_an_abandon(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    """A failed run's leftovers keep the slot held (`release`); once tidied and released it is `done`, and `start` answers
    with its result without a launch or a repeat; abandoned, it is `start` again, and `start` admits a fresh attempt."""

    def failed(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        slot.write_file("docs/design/tl-1/x.md", "x")
        worker = Worker(pid=42, pgid=42, start="native-start", boot="boot")
        return FakeRun(RunOutcome(rc=1, worker=worker, summary=Summary(text="", rc=1, stands=True)))(harness, spec, timeout, hooks)

    store = PlanStore(lambda: registered)
    attempts = PlanAttempts(store, PlanFiles(tmp_path), lambda: ("/bin/codex", {}), failed, lambda: 10, checkouts, slot_files)
    assert attempts.execute(KEY, ENTRY).status == "collected"
    reads = Reads(store, observe("gone", []), lambda: 10, nothing_left, lambda: "boot")

    def shown() -> AttemptStatus:
        found = status(reads, tmp_path / "art", "tasks", "tl-1")
        assert isinstance(found, Shown)
        return found.status

    assert shown().next == "release"
    held = releaser(store, checkouts, slot_files).release(KEY, False)
    assert isinstance(held, NotReleased) and held.reason == "slot_dirty" and shown().next == "release"
    slot.remove_file("docs/design/tl-1/x.md")
    assert isinstance(releaser(store, checkouts, slot_files).release(KEY, False), Released)
    assert (shown().next, shown().release is not None) == ("done", True)
    launcher, repeats = Launcher(Launched(KEY, ENTRY)), Repeats()
    ports = Starting(store, Admission(AdmitRefused("task")), launcher, lambda: 10, repeats)
    answered = start(ports, REQUEST)
    assert answered == Started("already_dispatched", "tasks", "tl-1", "attempt", True, result="run:worker_failed")
    assert (launcher.calls, repeats.calls) == ([], [])
    assert isinstance(releaser(store, checkouts, slot_files).release(KEY, True), Released)
    abandoned = shown()
    assert abandoned.next == "start" and abandoned.release is not None and abandoned.release.abandoned
    fresh = AttemptKey("fresh", "token", 2)
    admission = Admission(Admitted(fresh, "s1"))
    assert start(Starting(store, admission, Launcher(Launched(fresh, ENTRY)), lambda: 10, repeats), REQUEST) == Started(
        "started", "tasks", "tl-1", "fresh", False, ENTRY
    )
    assert len(admission.requests) == 1


def test_list_shows_one_row_per_task_its_latest_attempt_and_show_names_the_abandoned_one(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree
) -> None:
    registered.execute("INSERT INTO plan_release SELECT attempt_id,dispatch_token,generation,slot_head,5,1,'unclaimed' FROM plan_attempt")
    registered.execute("UPDATE reservation SET attempt_id='fresh',generation=2")
    registered.execute(
        """INSERT INTO plan_attempt (attempt_id,dispatch_token,generation,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,
        input_digest,schema_version,model,effort,sandbox,deadline,number,seq,slot_head)
        SELECT 'fresh','token',2,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,schema_version,model,effort,
        sandbox,deadline,1,2,slot_head FROM plan_attempt WHERE attempt_id='attempt'"""
    )
    reads = Reads(PlanStore(lambda: registered), observe("gone", []), lambda: 10, nothing_left, lambda: "boot")
    listed = attempts_status(reads)
    assert isinstance(listed, Listed) and [(each.attempt_id, each.seq, each.next) for each in listed.attempts] == [("fresh", 2, "start")]
    found = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(found, Shown) and (found.status.attempt_id, found.status.earlier) == ("fresh", (("attempt", "abandoned"),))
    assert found.status.release is None and found.status.number == 1


def test_an_abandon_whose_claim_is_still_unclaiming_says_release_and_start_refuses(registered: sqlite3.Connection, tmp_path: Path) -> None:
    registered.execute("DELETE FROM reservation")
    registered.execute("INSERT INTO plan_release SELECT attempt_id,dispatch_token,generation,slot_head,5,1,'unclaiming' FROM plan_attempt")
    store = PlanStore(lambda: registered)
    found = status(Reads(store, observe("gone", []), lambda: 10, nothing_left, lambda: "boot"), tmp_path / "art", "tasks", "tl-1")
    assert isinstance(found, Shown) and found.status.next == "release"
    admission, launcher = Admission(Admitted(AttemptKey("fresh", "token", 2), "s1")), Launcher(Launched(KEY, ENTRY))
    assert start(Starting(store, admission, launcher, lambda: 10, Repeats()), REQUEST) == Failed("refused", "release", UNCLAIMING)
    assert (admission.requests, launcher.calls) == ([], [])


def test_verify_reports_a_failed_publication_without_changing_its_result(reader: PlanStore) -> None:
    publishes = Publishes(NotPublished("unavailable", "remote"))
    checked = verify_task(reader, Verifier(Verified("blob")), Releases(), publishes, "tasks", "tl-1")
    assert checked == Checked("verified", "tasks", "tl-1", "attempt", "released", "unavailable:remote") and exit_code(checked) == 0


@pytest.mark.parametrize("result, expected, code", [
    (BranchPublished("x" * 40, "y" * 40), PublishedTask("tasks", "tl-1", "attempt", BranchPublished("x" * 40, "y" * 40)), 0),
    (NotPublished("refused", "diverged", "d"), Failed("refused", "diverged", "d"), 1),
    (NotPublished("unavailable", "remote", "r"), Failed("unavailable", "remote", "r"), 3),
])
def test_publish_task_maps_every_result_and_its_exit_code(
    reader: PlanStore, result: PublishResult, expected: PublishedTask | Failed, code: int
) -> None:
    publishes = Publishes(result)
    found = publish_task(reader, publishes, "tasks", "tl-1")
    assert (found, exit_code(found), publishes.keys) == (expected, code, [KEY])
    assert publish_task(reader, publishes, "tasks", "tl-9") == Failed("refused", "absent", "No attempt for tl-9 in backlog tasks")


def test_a_verified_plan_is_release_first_then_publish_then_done(
    registered: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    path = "docs/design/tl-1/plan.md"

    def agent(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        slot.write_file(path, "# Plan\n")
        text = json.dumps({"disposition": "planned", "plan_path": path, "paths": [path], "message": "Plan", "explanation": "done"})
        worker = Worker(pid=42, pgid=42, start="native-start", boot="boot")
        return FakeRun(RunOutcome(rc=0, worker=worker, summary=Summary(text=text, rc=0, stands=True)))(harness, spec, timeout, hooks)

    store = PlanStore(lambda: registered)
    attempts = PlanAttempts(store, PlanFiles(tmp_path), lambda: ("/bin/codex", {}), agent, lambda: 10, checkouts, slot_files)
    assert attempts.execute(KEY, ENTRY).reason == "verification"
    verifier = PlanVerifier(store, checkouts, slot_files, gone, lambda: 20, hold)
    reads = Reads(store, observe("gone", []), lambda: 10, nothing_left, lambda: "boot")

    def shown() -> AttemptStatus:
        found = status(reads, tmp_path / "art", "tasks", "tl-1")
        assert isinstance(found, Shown)
        return found.status

    held = NotReleased("unavailable", "slot_busy")
    assert verify_task(store, verifier, Releases(held), Publishes(), "tasks", "tl-1") == Checked(
        "verified", "tasks", "tl-1", "attempt", "unavailable:slot_busy", "published")  # the stub publishes nothing
    assert shown().next == "release"  # freeing the slot comes first
    assert isinstance(releaser(store, checkouts, slot_files).release(KEY, False), Released)
    assert (shown().next, shown().published) == ("publish", None)
    x = next(ref.sha for ref in slot.repo.refs(["refs/heads/task/"]) if ref.name == "refs/heads/task/tl-1")
    found = publish_task(store, PlanPublish(store, checkouts, slot_files, lambda: 40), "tasks", "tl-1")
    assert found == PublishedTask("tasks", "tl-1", "attempt", BranchPublished(x, x))
    assert (shown().next, shown().published) == ("done", PublishedRow(x, x, 40.0))


@pytest.mark.parametrize("stopped, word, code", [
    ("", "started", 0),
    ("no_free_slot", "refused:claimed_elsewhere", 0),
    ("", "verified release=unavailable:slot_busy branch=published", 0),  # a held release: as verify's own exit
    ("", "verified release=released branch=unavailable:remote", 3),  # as a publish move's
    ("", "claim_leaked", 0),
    ("", "unavailable:ancestry", 3),
    ("", "unavailable:store", 3),
    ("", "uncertain:launch", 3),
    ("", "unknown", 3),
    ("unavailable:tracker", "started", 3),
    ("refused:checkout", "started", 1),
])
def test_a_rounds_exit_code(stopped: str, word: str, code: int) -> None:
    assert exit_code(Round("tasks", (Move("tl-1", "start", word),), stopped)) == code


@pytest.mark.parametrize("reason, code", [("interrupted", 0), ("abrupt", 130), ("refused:database", 1), ("refused:schema", 1)])
def test_a_rounds_end_exit_code(reason: str, code: int) -> None:
    assert exit_code(Ended("tasks", reason)) == code
