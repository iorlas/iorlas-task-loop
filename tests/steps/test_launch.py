"""The launcher on a real factory.db file and real files, with a start fake that honours popen_registered's contract."""

import errno
import os
import sqlite3
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest
from sqlite_store import Store
from stream_proc import (
    IdentityUnavailableError,
    OwnedProcess,
    ProcessObservation,
    RegisteredStartUncertainError,
    observe_owned,
    popen_registered,
)

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import REGISTRATION_BUSY_MS, AttemptStore
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS, AttemptKey, EntryIdentity
from taskloop.check_store import CheckStore
from taskloop.composition import open_checks_launcher, open_launcher
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.ids import NativeIds
from taskloop.launch import CHECK_ENTRY_MODULE, AlreadyRunning, Launched, Launcher, LaunchRefused, LaunchUnavailable, LaunchUncertain

KEY = AttemptKey("attempt", "dispatch", 1)
NEW = OwnedProcess(9, 9, "new-start", "boot")
OLD = (7, "old-start", "boot")


class Pipe:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class Child:
    def __init__(self) -> None:
        self.stdin, self.stdout = Pipe(), Pipe()


class FakeStart:
    """popen_registered's contract without a process: failures before the callback register nothing, a raising callback
    means no permit and no exec, an exec failure after the commit is a plain OSError, a failed permit is Uncertain."""

    def __init__(self, mode: str = "exec", before: Callable[[], object] = lambda: None, identity: OwnedProcess = NEW) -> None:
        self.mode, self.before, self.identity = mode, before, identity
        self.calls: list[dict[str, object]] = []
        self.permitted = False
        self.after: Callable[[], object] = lambda: None
        self.child = Child()

    def __call__(
        self,
        argv: Sequence[str],
        *,
        registered: Callable[[OwnedProcess], None],
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stderr: int = -1,
        start_new_session: bool = True,
        registration_timeout: float = 5.0,
    ) -> tuple[Child, OwnedProcess]:
        os.fstat(stderr)  # the entry log is open while the child starts
        self.calls.append(
            {"argv": list(argv), "cwd": cwd, "env": env, "session": start_new_session, "timeout": registration_timeout, "fd": stderr}
        )
        failures: dict[str, BaseException] = {
            "popen": OSError(errno.EMFILE, "Too many open files"),
            "bootstrap": RuntimeError("Isolated process bootstrap failed before registration"),
            "timeout": TimeoutError(),
            "identity": IdentityUnavailableError("no identity"),
        }
        if self.mode in failures:
            raise failures[self.mode]
        self.before()
        registered(self.identity)  # a raising callback propagates: the library cleans the child, which never execs
        self.after()
        self.permitted = True
        if self.mode == "exec_failed":
            raise OSError(errno.ENOENT, "No such file or directory", argv[0])
        if self.mode == "uncertain":
            raise RegisteredStartUncertainError(self.identity, leader_reaped=True)
        return self.child, self.identity


class Observe:
    def __init__(self, kind: str = "gone") -> None:
        self.kind = kind
        self.seen: list[OwnedProcess] = []

    def __call__(self, identity: OwnedProcess) -> ProcessObservation:
        self.seen.append(identity)
        if self.kind == "gone":
            return ProcessObservation("gone")
        if self.kind == "unknown":
            return ProcessObservation("unknown")
        if self.kind == "different_process":
            return ProcessObservation("different_process", OwnedProcess(identity.pid, 1, "other", identity.boot))
        return ProcessObservation("matching", identity)


def launcher(db: Path, start: FakeStart, observe: Observe | None = None, now: float = 10) -> Launcher:
    return Launcher(db, EvidenceFiles(db.parent), lambda: now, start, observe or Observe(), "/venv/bin/python",
                    read_seconds=DEFAULT_GIT_READ_SECONDS, ids=NativeIds())


def stored(db: Path) -> tuple[object, ...]:
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT entry_pid,entry_start,entry_boot,phase FROM attempt").fetchone()
    finally:
        con.close()


def register(db: Path, entry: EntryIdentity) -> None:
    store = Store(SCHEMA)
    con = store.open_rw(db)
    assert con is not None
    assert AttemptStore(lambda: con, store.begin_immediate).register_entry(KEY, entry, 10) == "accepted"
    con.close()


def test_the_launchers_git_bound_is_in_the_entry_argv(admitted: Path) -> None:
    start = FakeStart()
    built = Launcher(admitted, EvidenceFiles(admitted.parent), lambda: 10, start, Observe(),
        "/venv/bin/python", read_seconds=45, ids=NativeIds())
    assert isinstance(built.launch("tasks", "tl-1", 30), Launched)
    argv = start.calls[0]["argv"]
    assert isinstance(argv, list) and argv[-3:] == ["45", "tasks", "tl-1"]


def test_launch_registers_before_the_permit_and_leaves_the_child_alone(admitted: Path) -> None:
    seen: list[tuple[object, ...]] = []
    start = FakeStart()
    start.before = lambda: seen.append(stored(admitted))
    result = launcher(admitted, start).launch("tasks", "tl-1", 30)
    assert result == Launched(KEY, (9, "new-start", "boot"))
    assert seen == [(None, None, None, "admitted")] and stored(admitted) == (9, "new-start", "boot", "admitted")
    call = start.calls[0]
    root = str(admitted.parent)
    assert call["argv"] == ["/venv/bin/python", "-I", "-m", "taskloop.attempt_entry", str(admitted), root, "600", "tasks", "tl-1"]
    assert KEY.dispatch_token not in str(call["argv"])  # the dispatch token is never in argv
    assert (call["cwd"], call["env"], call["session"], call["timeout"]) == (root, None, True, 5.0)
    assert start.child.stdin.closed and start.child.stdout.closed
    log = admitted.parent / EvidenceFiles(admitted.parent).directory(KEY) / "entry.log"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    fd = call["fd"]
    assert isinstance(fd, int)
    with pytest.raises(OSError):
        os.fstat(fd)  # the coordinator's copy of the log descriptor is closed


@pytest.mark.parametrize("mode", ["popen", "bootstrap", "timeout", "identity"])
def test_a_start_failure_before_the_callback_registers_nothing(admitted: Path, mode: str) -> None:
    assert launcher(admitted, FakeStart(mode)).launch("tasks", "tl-1", 30) == LaunchUnavailable("start")
    assert stored(admitted) == (None, None, None, "admitted")


def test_a_refused_callback_never_permits_the_target(admitted: Path) -> None:
    start = FakeStart(before=lambda: register(admitted, OLD))  # another launcher registered between read and callback
    assert launcher(admitted, start).launch("tasks", "tl-1", 30) == LaunchRefused("registration_conflict")
    assert not start.permitted and stored(admitted)[:3] == OLD
    expired = FakeStart()
    other = launcher(admitted, expired, observe=Observe("gone"), now=100).launch("tasks", "tl-1", 30)
    assert other == LaunchRefused("registration_refused") and not expired.permitted and stored(admitted)[:3] == OLD


def test_exec_failure_after_the_commit_leaves_a_dead_entry_that_the_next_launch_replaces(admitted: Path) -> None:
    assert launcher(admitted, FakeStart("exec_failed")).launch("tasks", "tl-1", 30) == LaunchUnavailable("exec_failed_after_commit")
    assert stored(admitted)[:3] == (9, "new-start", "boot")
    observe, later = Observe("gone"), OwnedProcess(11, 11, "later-start", "boot")
    assert launcher(admitted, FakeStart(identity=later), observe).launch("tasks", "tl-1", 30) == Launched(KEY, (11, "later-start", "boot"))
    assert observe.seen == [NEW] and stored(admitted)[:3] == (11, "later-start", "boot")


def test_restart_between_entry_registration_and_permission_keeps_the_durable_identity(admitted: Path) -> None:
    start = FakeStart()

    def crash() -> None:
        assert stored(admitted)[:3] == (NEW.pid, NEW.start, NEW.boot)
        assert not start.permitted
        raise RuntimeError("entry registration committed; permit not sent")

    start.after = crash
    assert launcher(admitted, start).launch("tasks", "tl-1", 30) == LaunchUnavailable("exec_failed_after_commit")
    assert not start.permitted
    later = OwnedProcess(11, 11, "later-start", "boot")
    assert launcher(admitted, FakeStart(identity=later)).launch("tasks", "tl-1", 30) == Launched(KEY, (11, "later-start", "boot"))


@pytest.mark.parametrize("kind", ["gone", "different_process"])
def test_an_observed_dead_entry_is_replaced(admitted: Path, kind: str) -> None:
    register(admitted, OLD)
    observe = Observe(kind)
    assert launcher(admitted, FakeStart(), observe).launch("tasks", "tl-1", 30) == Launched(KEY, (9, "new-start", "boot"))
    assert observe.seen == [OwnedProcess(7, 7, "old-start", "boot")] and stored(admitted)[:3] == (9, "new-start", "boot")


def test_a_relaunch_after_a_reboot_renews_the_deadline_from_its_minutes(admitted: Path) -> None:
    """A reboot cannot be run here: the stored entry carries another boot id than the started child's ("boot")."""
    register(admitted, (7, "old-start", "old-boot"))
    start = FakeStart()
    found = launcher(admitted, start, Observe("different_process"), now=200).launch("tasks", "tl-1", 30)
    assert found == Launched(KEY, (9, "new-start", "boot")) and start.permitted
    con = sqlite3.connect(admitted)
    try:
        assert con.execute("SELECT deadline FROM attempt").fetchone() == (200 + 30 * 60,)
    finally:
        con.close()


def test_minutes_no_float_holds_refuse_the_renewal_and_keep_the_stored_entry(admitted: Path) -> None:
    register(admitted, (7, "old-start", "old-boot"))
    start = FakeStart()
    found = launcher(admitted, start, Observe("different_process"), now=200).launch("tasks", "tl-1", 10**400)
    assert found == LaunchRefused("registration_refused") and not start.permitted
    assert stored(admitted)[:3] == (7, "old-start", "old-boot")


@pytest.mark.parametrize(("kind", "expected"), [("matching", AlreadyRunning(KEY, OLD)), ("unknown", LaunchUnavailable("observe"))])
def test_a_live_or_unobservable_entry_is_not_started_again(admitted: Path, kind: str, expected: object) -> None:
    register(admitted, OLD)
    start = FakeStart()
    assert launcher(admitted, start, Observe(kind)).launch("tasks", "tl-1", 30) == expected
    assert start.calls == [] and stored(admitted)[:3] == OLD


def test_uncertain_permit_names_the_registered_identity(admitted: Path) -> None:
    assert launcher(admitted, FakeStart("uncertain")).launch("tasks", "tl-1", 30) == LaunchUncertain(KEY, (9, "new-start", "boot"))
    assert stored(admitted)[:3] == (9, "new-start", "boot")


def test_only_an_admitted_attempt_of_a_known_task_launches(admitted: Path) -> None:
    start = FakeStart()
    assert launcher(admitted, start).launch("tasks", "tl-9", 30) == LaunchRefused("absent")
    con = sqlite3.connect(admitted)
    con.execute("UPDATE attempt SET phase='dispatching',base_commit=?", ("b" * 40,))
    con.commit()
    con.close()
    assert launcher(admitted, start).launch("tasks", "tl-1", 30) == LaunchRefused("dispatched")
    assert start.calls == []


def test_a_missing_database_is_refused_and_never_created(tmp_path: Path) -> None:
    db = tmp_path / "factory.db"
    start = FakeStart()
    assert launcher(db, start).launch("tasks", "tl-1", 30) == LaunchRefused("database")
    assert not db.exists() and start.calls == []


def test_a_foreign_schema_version_is_unavailable(admitted: Path) -> None:
    con = sqlite3.connect(admitted)
    con.execute("PRAGMA user_version=9")
    con.close()
    start = FakeStart()
    assert launcher(admitted, start).launch("tasks", "tl-1", 30) == LaunchUnavailable("store")
    assert start.calls == []


def test_composition_starts_with_the_released_registered_start(tmp_path: Path) -> None:
    built = open_launcher(tmp_path / "factory.db", tmp_path, GitViews(45))
    assert built.start is popen_registered and built.observe is observe_owned and built.executable == sys.executable
    assert built.read_seconds == 45
    assert open_launcher(Path("factory.db"), tmp_path, GitViews(DEFAULT_GIT_READ_SECONDS)).database == Path.cwd() / "factory.db"


def test_a_relative_database_is_refused_before_any_read_registration_or_start(admitted: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(admitted.parent)
    start = FakeStart()
    built = Launcher(Path(admitted.name), EvidenceFiles(admitted.parent), lambda: 10, start, Observe(), "/venv/bin/python",
                     read_seconds=DEFAULT_GIT_READ_SECONDS, ids=NativeIds())
    assert built.launch("tasks", "tl-1", 30) == LaunchRefused("database")
    assert start.calls == [] and stored(admitted) == (None, None, None, "admitted")


def test_an_unopenable_entry_log_starts_nothing(admitted: Path) -> None:
    (admitted.parent / "attempts").write_text("not a directory")
    start = FakeStart()
    assert launcher(admitted, start).launch("tasks", "tl-1", 30) == LaunchUnavailable("log")
    assert start.calls == [] and stored(admitted) == (None, None, None, "admitted")


def test_the_registration_write_waits_briefly_and_a_busy_store_registers_nothing(admitted: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[object] = []

    def busy(store: AttemptStore, *_args: object, **_named: object) -> str:
        con = store.connect()
        assert con is not None
        waits.append(con.execute("PRAGMA busy_timeout").fetchone()[0])
        raise StoreUnavailable("Factory database operation failed")  # what a write lock held past the wait raises

    monkeypatch.setattr(AttemptStore, "register_entry", busy)
    start = FakeStart()
    assert launcher(admitted, start).launch("tasks", "tl-1", 30) == LaunchUnavailable("store")
    assert waits == [REGISTRATION_BUSY_MS] and not start.permitted and stored(admitted) == (None, None, None, "admitted")


CHECKS = AttemptKey("checks", "checks-token", 1)


def checks_launcher(db: Path, start: FakeStart, observe: Observe | None = None, now: float = 10) -> Launcher:
    return Launcher(db, EvidenceFiles(db.parent), lambda: now, start, observe or Observe(), "/venv/bin/python", CheckStore,
                    CHECK_ENTRY_MODULE, read_seconds=DEFAULT_GIT_READ_SECONDS, ids=NativeIds())


def checks_row(db: Path) -> tuple[object, ...]:
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT entry_pid,entry_start,entry_boot,deadline FROM checks_attempt").fetchone()
    finally:
        con.close()


def test_a_checks_attempt_past_its_deadline_is_still_launched_to_conclude_expired(on_slot: Path) -> None:
    """`CheckStore`'s registration has no deadline refusal; the agent attempts' launcher keeps its own."""
    start = FakeStart()
    assert checks_launcher(on_slot, start, now=500).launch("tasks", "tl-1", 30) == Launched(CHECKS, (9, "new-start", "boot"))
    assert start.permitted and checks_row(on_slot) == (9, "new-start", "boot", 100.0)
    argv = start.calls[0]["argv"]
    assert argv == ["/venv/bin/python", "-I", "-m", "taskloop.check_entry", str(on_slot), str(on_slot.parent), "600", "tasks", "tl-1"]
    log = on_slot.parent / EvidenceFiles(on_slot.parent).directory(CHECKS) / "entry.log"
    assert log.exists()  # the checks attempt's own entry log
    observe = Observe("matching")
    assert checks_launcher(on_slot, FakeStart(), observe).launch("tasks", "tl-1", 30) == AlreadyRunning(CHECKS, (9, "new-start", "boot"))


@pytest.mark.parametrize("change", ["UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=1",
                                    "UPDATE checks_attempt SET released_at=1,parked=slot_head,abandoned=1"], ids=["concluded", "released"])
def test_only_an_admitted_unreleased_checks_attempt_launches(on_slot: Path, change: str) -> None:
    start = FakeStart()
    assert checks_launcher(on_slot, start).launch("tasks", "tl-9", 30) == LaunchRefused("absent")
    con = sqlite3.connect(on_slot)
    con.execute(change)
    con.commit()
    con.close()
    assert checks_launcher(on_slot, start).launch("tasks", "tl-1", 30) == LaunchRefused("dispatched") and start.calls == []


def test_composition_launches_checks_attempts_with_their_store_and_entry(tmp_path: Path) -> None:
    built = open_checks_launcher(tmp_path / "factory.db", tmp_path, GitViews(45))
    assert (built.targets, built.module, built.start) == (CheckStore, CHECK_ENTRY_MODULE, popen_registered)
    assert open_launcher(tmp_path / "factory.db", tmp_path, GitViews(45)).module == "taskloop.attempt_entry"
