"""The plan commands' operations over a real factory.db file (read-only where the command is) with recording admission,
launcher and verifier fakes and a fake entry observation: no process is started or inspected."""

import json
import sqlite3
from collections.abc import Callable, Generator
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
    Adoption,
    Checked,
    EntryState,
    Failed,
    Listed,
    Next,
    Reads,
    Seen,
    Shown,
    Started,
    Starting,
    StartRequest,
    attempts_status,
    last_entry,
    next_step,
    start,
    status,
    verify_task,
)
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore
from taskloop.plan_types import (
    AttemptKey,
    AttemptResult,
    Checkouts,
    NotApplicable,
    Rejected,
    SlotFiles,
    Unsettled,
    Verified,
    VerifyRefused,
    VerifyResult,
    VerifyUnavailable,
)
from taskloop.plan_verifier import PlanVerifier
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

    def launch(self, backlog: str, task_id: str) -> LaunchResult:
        self.calls.append((backlog, task_id))
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
    assert launcher.calls == [("tasks", "tl-1")]


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
    shown = status(Reads(reader, observe(seen, calls), lambda: now, nothing_left), tmp_path / "art", "tasks", "tl-1")
    assert isinstance(shown, Shown)
    assert (shown.status.entry, shown.status.next, shown.status.deadline_passed) == (entry, expected, now >= 100)
    assert calls == [ENTRY]
    assert (shown.status.entry_process, shown.status.worker) == (ENTRY, None)
    write(admitted, "UPDATE plan_attempt SET phase='dispatching',base_commit=?,worker_pid=42,worker_pgid=41", "a" * 40)
    again = status(Reads(reader, observe(seen, calls), lambda: now, nothing_left), tmp_path / "art", "tasks", "tl-1")
    assert isinstance(again, Shown) and again.status.worker == (42, 41)


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
    shown = status(Reads(reader, observe("gone", []), lambda: 10, nothing_left), tmp_path / "art", "tasks", "tl-1")
    assert isinstance(shown, Shown)
    directory = PlanFiles(tmp_path / "art").root / PlanFiles(tmp_path / "art").directory(KEY)
    assert (shown.directory, shown.entry_log) == (directory, directory / "entry.log")
    assert (shown.status.entry, shown.status.next, shown.status.result) == ("none", "start", AttemptResult("pending", "admitted"))
    assert (files(), rows()) == (before, stored)
    assert not (tmp_path / "art").exists()
    assert status(Reads(reader, observe("gone", []), lambda: 10, nothing_left), tmp_path / "art", "tasks", "tl-2") == Failed(
        "refused", "absent", "No attempt for tl-2 in backlog tasks"
    )


@pytest.mark.parametrize("now, stuck, rows", [(10, False, 1), (10, True, 0), (200, True, 1)])
def test_list_keeps_only_stuck_or_unknown_when_asked(reader: PlanStore, now: float, stuck: bool, rows: int) -> None:
    listed = attempts_status(Reads(reader, observe("gone", []), lambda: now, nothing_left), stuck=stuck)
    assert isinstance(listed, Listed) and len(listed.attempts) == rows


@pytest.mark.parametrize("verdict, expected", [
    (Verified("blob"), Checked("verified", "tasks", "tl-1", "attempt")),
    (Verified("blob", reused=True), Checked("reused", "tasks", "tl-1", "attempt")),
    (Rejected("paths"), Failed("rejected", "paths")),
    (NotApplicable("incomplete"), Failed("not_applicable", "incomplete")),
    (VerifyRefused("session"), Failed("refused", "session")),
    (Unsettled("dirty"), Failed("unsettled", "dirty")),
    (VerifyUnavailable("git:NotARepo"), Failed("unavailable", "git:NotARepo")),
    (VerifyUnavailable("inconsistent"), Failed("defect", "inconsistent")),
])
def test_verify_maps_every_verdict(reader: PlanStore, verdict: VerifyResult, expected: Checked | Failed) -> None:
    verifier = Verifier(verdict)
    assert verify_task(reader, verifier, "tasks", "tl-1") == expected
    assert verifier.keys == [KEY]
    absent = Verifier(verdict)
    assert verify_task(reader, absent, "tasks", "tl-9") == Failed("refused", "absent", "No attempt for tl-9 in backlog tasks")
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
    first = verify_task(store, PlanVerifier(store, checkouts, slot_files, gone, lambda: 20), "tasks", "tl-1")
    assert first == Checked("verified", "tasks", "tl-1", "attempt")
    slot.repo.drop_checkout(slot.path)
    opened: list[Path] = []

    def counted(where: Path) -> Repo:
        opened.append(where)
        return checkouts(where)

    assert verify_task(store, PlanVerifier(store, counted, slot_files, gone, lambda: 20), "tasks", "tl-1") == first
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
    verifier = PlanVerifier(store, checkouts, slot_files, gone, lambda: 20)
    reads = Reads(store, observe("gone", []), lambda: 10, verifier.leftovers)
    before = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(before, Shown) and (before.status.next, before.status.leftovers) == ("verify", ())  # nothing committed yet
    assert verify_task(store, verifier, "tasks", "tl-1") == Failed("unsettled", "uncommitted", f"?? {stray}")  # as show lists it
    shown = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(shown, Shown) and shown.status.next == "repeat"
    assert (shown.status.result.status, shown.status.result.reason) == ("pending", "repeat")
    assert shown.status.leftovers == ("uncommitted", f"?? {stray}")
    probed: list[AttemptKey] = []

    def counted(key: AttemptKey) -> Unsettled | None:
        probed.append(key)
        return verifier.leftovers(key)

    counting = Reads(store, observe("gone", []), lambda: 10, counted)
    assert attempts_status(counting, stuck=True) == Listed(()) and probed == []  # no Git read for a filtered-out attempt
    listed = attempts_status(counting)
    assert isinstance(listed, Listed) and [each.next for each in listed.attempts] == ["repeat"] and probed == [KEY]
    slot.remove_file(stray)
    tidied = status(reads, tmp_path / "art", "tasks", "tl-1")
    assert isinstance(tidied, Shown) and (tidied.status.next, tidied.status.leftovers) == ("verify", ())


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


@pytest.mark.parametrize("version", [1, 2, 3, 4, 6])
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


@pytest.mark.parametrize(("tail", "expected"), [
    (None, None),
    ("", None),
    ("refused slot_staged verify=refused:not_captured\n", "refused slot_staged verify=refused:not_captured"),
    ("unavailable credentials:auth verify=refused:not_captured\nnoise\n", "unavailable credentials:auth verify=refused:not_captured"),
    ("collected verified verify=verified\nrefused \x1b]0;owned\x07\n", "collected verified verify=verified"),
    ("refused slot_staged\x9b31m\n", None),
    ("Traceback (most recent call last):\n", None),
    ("failed TypeError\n", "failed TypeError"),
    ("refused " + "x" * 61 + "\n", None),
    ("refused a b c d e f g\n", None),
])
def test_only_a_line_of_the_entrys_fixed_words_is_shown(tail: str | None, expected: str | None) -> None:
    assert last_entry(tail) == expected
