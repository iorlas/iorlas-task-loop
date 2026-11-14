"""Launch an admitted attempt into its own surviving entry process, registered before the entry may run.

The launcher starts the entry module (`python -I -m taskloop.attempt_entry` for an agent attempt, `taskloop.check_entry`
for a checks attempt) through the injected registered start: the start calls back with the child's boot-aware identity,
and the target runs only after its store's `register_entry` committed it. The store is the `EntryTargets` port
(`AttemptStore`, or `CheckStore`, whose registration has no deadline refusal: an expired checks attempt is launched to
conclude `expired` and release its slot). The launcher never writes to, waits on, signals or kills the child; it closes
its pipes and leaves it in its own session.
"""

import math
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from sqlite_store import Store
from stream_proc import IdentityUnavailableError, OwnedProcess, ProcessObservation, RegisteredStartUncertainError

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import REGISTRATION_BUSY_MS, AttemptStore
from taskloop.attempt_types import AttemptKey, EntryIdentity, Replaced, entry_identity
from taskloop.drain.actions import Fenced, Unobservable, operation
from taskloop.drain.models import ActionKind, Identity, Reason
from taskloop.drain.store import DrainStore
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.ids import Ids
from taskloop.recovery.models import Outcome, Result

REGISTRATION_TIMEOUT = 5.0  # stated, not padded: the callback is bounded at REGISTRATION_BUSY_MS plus one short write
ENTRY_MODULE = "taskloop.attempt_entry"
CHECK_ENTRY_MODULE = "taskloop.check_entry"


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


type ObserveProcess = Callable[[OwnedProcess], ProcessObservation]


class EntryTargets(Protocol):
    """The store whose attempts the launcher starts: the task's current attempt with its state (only `admitted`
    launches) and registered entry, and the entry's one registration write."""

    def attempt_of(self, backlog: str, task_id: str) -> tuple[AttemptKey, str, EntryIdentity | None] | None: ...

    def register_entry(
        self, key: AttemptKey, entry: EntryIdentity, now: float, replacing: Replaced | None = None, renewed: float | None = None,
    ) -> Literal["accepted", "conflict", "refused"]: ...


type Connect = Callable[[], sqlite3.Connection | None]
type Begin = Callable[[sqlite3.Connection], AbstractContextManager[None]]
type Targets = Callable[[Connect, Begin], EntryTargets]


@dataclass(frozen=True)
class Launched:
    key: AttemptKey
    entry: EntryIdentity


@dataclass(frozen=True)
class AlreadyRunning:
    key: AttemptKey
    entry: EntryIdentity


@dataclass(frozen=True)
class LaunchRefused:
    reason: Literal["database", "absent", "dispatched", "registration_conflict", "registration_refused"] | Reason | Outcome
    explanation: str = ""


@dataclass(frozen=True)
class LaunchUnavailable:
    """Nothing runs. `store`, `observe`, `log` and `start` registered nothing; after `exec_failed_after_commit` the row
    names a process that never ran the entry, which the next launch observes and replaces."""

    reason: Literal["store", "observe", "log", "start", "exec_failed_after_commit"]


@dataclass(frozen=True)
class LaunchUncertain:
    """The permit was being sent: the registered entry may run. A later launch observes it."""

    key: AttemptKey
    entry: EntryIdentity


type LaunchResult = Launched | AlreadyRunning | LaunchRefused | LaunchUnavailable | LaunchUncertain


class _CallbackRefused(Exception):
    def __init__(self, refusal: LaunchRefused) -> None:
        super().__init__(refusal.reason)
        self.refusal = refusal


def entry_process(entry: EntryIdentity) -> OwnedProcess:
    """The one identity rule for a registered entry: a new session makes it its own group leader, so its pgid is its pid."""
    return OwnedProcess(entry[0], entry[0], entry[1], entry[2])


class Launcher:
    def __init__(
        self, database: Path, files: EvidenceFiles, clock: Callable[[], float], start: Start, observe: ObserveProcess, executable: str,
        targets: Targets = AttemptStore, module: str = ENTRY_MODULE,
        *, read_seconds: int, ids: Ids, recovery: Callable[[AttemptKey, Identity, float], Result] | None = None,
    ) -> None:
        """`targets` and `module`: the agent attempts' store and entry by default, `CheckStore` and `CHECK_ENTRY_MODULE`
        for checks attempts. `read_seconds`: the Git read bound the entry's views carry (argv)."""
        self.ids = ids
        self.database, self.files, self.clock = database, files, clock
        self.start, self.observe, self.executable = start, observe, executable
        self.targets, self.module, self.read_seconds = targets, module, read_seconds
        self.recovery = recovery

    def launch(self, backlog: str, task_id: str, minutes: int) -> LaunchResult:
        """Start the task's admitted attempt unless its registered entry still runs; never creates factory.db.

        A relative database path is refused before anything is read: the entry would refuse it after registration.
        `minutes`: a replacement of an entry registered in another boot renews the deadline to now plus these minutes in
        the registration's own write (`register_entry`), so a reboot mid-start continues with its full time."""
        if not self.database.is_absolute():
            return LaunchRefused("database")
        store = Store(SCHEMA)
        reader = writer = None
        try:
            reader = store.open_ro(self.database)
            if reader is None:
                return LaunchRefused("database")
            target = self._target(self.targets(lambda: reader, store.begin_immediate), backlog, task_id)
            if not isinstance(target, tuple):
                return target
            writer = store.open_rw(self.database)  # a file removed since the read-only open would be created here
            if writer is None:
                return LaunchUnavailable("store")
            writer.execute(f"PRAGMA busy_timeout={REGISTRATION_BUSY_MS}")
            drain = DrainStore(lambda: writer, store.begin_immediate, ids=self.ids)
            return self._authorized(drain, target, (backlog, task_id), self.targets(lambda: writer,
                store.begin_immediate), minutes)
        except (sqlite3.Error, StoreUnavailable):
            return LaunchUnavailable("store")
        finally:
            for con in (reader, writer):
                if con is not None:
                    con.close()

    def _authorized(self, drain: DrainStore, target: tuple[AttemptKey, Replaced | None, bool], task: tuple[str, str],
                    writer: EntryTargets, minutes: int) -> LaunchResult:
        try:
            with operation(drain, ActionKind.DISPATCH, ids=self.ids, subject=target[0].attempt_id):
                return self._start(target[0], task, writer, target[1], minutes, recovering=target[2])
        except Fenced:
            return LaunchRefused(Reason.DRAINING, "Dispatch is closed while the factory drains.")
        except Unobservable:
            return LaunchUnavailable("observe")

    def _target(self, reader: EntryTargets, backlog: str, task_id: str) -> tuple[AttemptKey, Replaced | None, bool] | LaunchResult:
        """The admitted attempt to start, and the stored entry it replaces once that is observed not to run."""
        found = reader.attempt_of(backlog, task_id)
        if found is None:
            return LaunchRefused("absent")
        key, phase, stored = found
        if phase != "admitted":
            return LaunchRefused("dispatched") if self.recovery is None else (key, None, True)
        if stored is None:
            return key, None, False
        seen = self.observe(entry_process(stored))  # pgid is not compared
        if seen.kind == "matching":
            return AlreadyRunning(key, stored)
        if seen.kind == "unknown":
            return LaunchUnavailable("observe")
        return key, Replaced(stored, seen.kind), False

    def _register(
        self, key: AttemptKey, identity: OwnedProcess, writer: EntryTargets, replacing: Replaced | None, minutes: int,
        *, recovering: bool,
    ) -> None:
        now = self.clock()
        try:
            renewed = float(now + minutes * 60)
        except OverflowError:  # no float holds it: the store refuses a non-finite renewal
            renewed = math.inf
        if recovering and self.recovery is not None:
            authorized = self.recovery(key, Identity(pid=identity.pid, pgid=identity.pgid, start=identity.start, boot=identity.boot),
                                       renewed)
            if authorized.outcome is not Outcome.AUTHORIZED:
                raise _CallbackRefused(LaunchRefused(authorized.outcome, authorized.explanation))
        else:
            answer = writer.register_entry(key, entry_identity(identity), now, replacing, renewed=renewed)
            if answer != "accepted":
                raise _CallbackRefused(LaunchRefused("registration_conflict" if answer == "conflict" else "registration_refused"))

    def _start(
        self, key: AttemptKey, task: tuple[str, str], writer: EntryTargets, replacing: Replaced | None, minutes: int,
        *, recovering: bool = False,
    ) -> LaunchResult:
        """`task` (backlog, task id) names the attempt to the entry; the dispatch token never enters argv."""
        committed = False

        def registered(identity: OwnedProcess) -> None:
            nonlocal committed
            self._register(key, identity, writer, replacing, minutes, recovering=recovering)
            committed = True

        argv = [self.executable, "-I", "-m", self.module, str(self.database), str(self.files.root), str(self.read_seconds), *task]
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
            return refused.refusal
        except StoreUnavailable:
            return LaunchUnavailable("store")
        except RegisteredStartUncertainError as uncertain:
            return LaunchUncertain(key, entry_identity(uncertain.identity))
        except (OSError, IdentityUnavailableError, RuntimeError):
            # before the commit nothing was registered and the library cleaned the child; after it, the exec failed
            return LaunchUnavailable("exec_failed_after_commit" if committed else "start")
        finally:
            os.close(log)
        for pipe in (child.stdin, child.stdout):
            if pipe is not None:
                pipe.close()
        return Launched(key, entry_identity(identity))
