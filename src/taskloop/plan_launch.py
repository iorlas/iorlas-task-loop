"""Launch an admitted plan attempt into its own surviving entry process, registered before the entry may run.

The launcher starts `python -I -m taskloop.attempt_entry` through the injected registered start: the start calls back
with the child's boot-aware identity, and the target runs only after `PlanStore.register_entry` committed it. The
launcher never writes to, waits on, signals or kills the child; it closes its pipes and leaves it in its own session.
"""

import math
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from sqlite_store import Store
from stream_proc import IdentityUnavailableError, OwnedProcess, ProcessObservation, RegisteredStartUncertainError

from taskloop.plan_files import EvidenceError, PlanFiles
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import REGISTRATION_BUSY_MS, PlanStore, StoreUnavailable
from taskloop.plan_types import AttemptKey, Replaced

REGISTRATION_TIMEOUT = 5.0  # stated, not padded: the callback is bounded at REGISTRATION_BUSY_MS plus one short write
ENTRY_MODULE = "taskloop.attempt_entry"


class Pipe(Protocol):
    def close(self) -> None: ...


class Child(Protocol):
    """The started child as the launcher sees it: two pipes to close, nothing to wait on."""

    @property
    def stdin(self) -> Pipe | None: ...

    @property
    def stdout(self) -> Pipe | None: ...


class Start(Protocol):
    """`stream_proc.popen_registered`'s signature, so neither this module nor a fake imports a process API."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        registered: Callable[[OwnedProcess], None],
        cwd: str | os.PathLike[str] | None = ...,
        env: Mapping[str, str] | None = ...,
        stderr: int = ...,
        start_new_session: bool = ...,
        registration_timeout: float = ...,
    ) -> tuple[Child, OwnedProcess]: ...


type Observe = Callable[[OwnedProcess], ProcessObservation]
type Entry = tuple[int, str, str]


@dataclass(frozen=True)
class Launched:
    key: AttemptKey
    entry: Entry


@dataclass(frozen=True)
class AlreadyRunning:
    key: AttemptKey
    entry: Entry


@dataclass(frozen=True)
class LaunchRefused:
    reason: Literal["database", "absent", "dispatched", "registration_conflict", "registration_refused"]


@dataclass(frozen=True)
class LaunchUnavailable:
    """Nothing runs. `store`, `observe`, `log` and `start` registered nothing; after `exec_failed_after_commit` the row
    names a process that never ran the entry, which the next launch observes and replaces."""

    reason: Literal["store", "observe", "log", "start", "exec_failed_after_commit"]


@dataclass(frozen=True)
class LaunchUncertain:
    """The permit was being sent: the registered entry may run. A later launch observes it."""

    key: AttemptKey
    entry: Entry


type LaunchResult = Launched | AlreadyRunning | LaunchRefused | LaunchUnavailable | LaunchUncertain


class _CallbackRefused(Exception):
    def __init__(self, reason: Literal["registration_conflict", "registration_refused"]) -> None:
        super().__init__(reason)
        self.reason: Literal["registration_conflict", "registration_refused"] = reason


def entry_process(entry: Entry) -> OwnedProcess:
    """The one identity rule for a registered entry: a new session makes it its own group leader, so its pgid is its pid."""
    return OwnedProcess(entry[0], entry[0], entry[1], entry[2])


def _entry(identity: OwnedProcess) -> Entry:
    return identity.pid, identity.start, identity.boot


class Launcher:
    def __init__(
        self, database: Path, files: PlanFiles, clock: Callable[[], float], start: Start, observe: Observe, executable: str
    ) -> None:
        self.database, self.files, self.clock = database, files, clock
        self.start, self.observe, self.executable = start, observe, executable

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        """Start the task's admitted attempt unless its registered entry still runs; never creates factory.db.

        A relative database path is refused before anything is read: the entry would refuse it after registration.
        `minutes`: a replacement of an entry registered in another boot renews the deadline to now plus these minutes in
        the registration's own write (`PlanStore.register_entry`), so a reboot mid-start continues with its full time."""
        if not self.database.is_absolute():
            return LaunchRefused("database")
        store = Store(SCHEMA)
        reader = writer = None
        try:
            reader = store.open_ro(self.database)
            if reader is None:
                return LaunchRefused("database")
            target = self._target(PlanStore(lambda: reader), backlog, task_id)
            if not isinstance(target, tuple):
                return target
            writer = store.open_rw(self.database)  # a file removed since the read-only open would be created here
            if writer is None:
                return LaunchUnavailable("store")
            writer.execute(f"PRAGMA busy_timeout={REGISTRATION_BUSY_MS}")
            return self._start(target[0], (backlog, task_id), PlanStore(lambda: writer, store.begin_immediate), target[1], minutes)
        except (sqlite3.Error, StoreUnavailable):
            return LaunchUnavailable("store")
        finally:
            for con in (reader, writer):
                if con is not None:
                    con.close()

    def _target(self, reader: PlanStore, backlog: str, task_id: str) -> tuple[AttemptKey, Replaced | None] | LaunchResult:
        """The admitted attempt to start, and the stored entry it replaces once that is observed not to run."""
        found = reader.attempt_of(backlog, task_id)
        if found is None:
            return LaunchRefused("absent")
        key, phase, stored = found
        if phase != "admitted":
            return LaunchRefused("dispatched")
        if stored is None:
            return key, None
        seen = self.observe(entry_process(stored))  # pgid is not compared
        if seen.kind == "matching":
            return AlreadyRunning(key, stored)
        if seen.kind == "unknown":
            return LaunchUnavailable("observe")
        return key, Replaced(stored, seen.kind)

    def _start(
        self, key: AttemptKey, task: tuple[str, str], writer: PlanStore, replacing: Replaced | None, minutes: int
    ) -> LaunchResult:
        """`task` (backlog, task id) names the attempt to the entry; the dispatch token never enters argv."""
        committed = False

        def registered(identity: OwnedProcess) -> None:
            nonlocal committed
            now = self.clock()
            try:
                renewed = float(now + minutes * 60)
            except OverflowError:  # no float holds it: the store refuses a non-finite renewal
                renewed = math.inf
            answer = writer.register_entry(key, _entry(identity), now, replacing, renewed=renewed)
            if answer != "accepted":
                raise _CallbackRefused("registration_conflict" if answer == "conflict" else "registration_refused")
            committed = True

        argv = [self.executable, "-I", "-m", ENTRY_MODULE, str(self.database), str(self.files.root), *task]
        try:
            log = os.open(self.files.entry_log(key), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
        except (EvidenceError, OSError):
            return LaunchUnavailable("log")
        try:
            child, identity = self.start(
                argv,
                registered=registered,
                cwd=str(self.files.root),
                env=None,
                stderr=log,
                start_new_session=True,
                registration_timeout=REGISTRATION_TIMEOUT,
            )
        except _CallbackRefused as refused:
            return LaunchRefused(refused.reason)
        except StoreUnavailable:
            return LaunchUnavailable("store")
        except RegisteredStartUncertainError as uncertain:
            return LaunchUncertain(key, _entry(uncertain.identity))
        except (OSError, IdentityUnavailableError, RuntimeError):
            # before the commit nothing was registered and the library cleaned the child; after it, the exec failed
            return LaunchUnavailable("exec_failed_after_commit" if committed else "start")
        finally:
            os.close(log)
        for pipe in (child.stdin, child.stdout):
            if pipe is not None:
                pipe.close()
        return Launched(key, _entry(identity))
