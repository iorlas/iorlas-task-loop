"""Construct the command surface's boundaries: the machine config file, the read-only factory.db guard, and the plan and
slot openers over `composition`'s real wiring. The attempt entry process never imports this module (.importlinter)."""

import os
import sqlite3
import sys
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from git_porcelain import GitUnavailable, NotARepo
from sqlite_store import Store

from taskloop.composition import (
    RealSlotFiles,
    adopt_slots,
    checkouts,
    entry_seen,
    open_launcher,
    open_plan_admission,
    open_plan_verifier,
    open_publisher,
    open_releaser,
    tracker_reads,
    worker_gone,
)
from taskloop.interrupts import installed
from taskloop.machine_config import ConfigRefused, Flags, Loaded, config_file, resolve
from taskloop.plan_files import PlanFiles
from taskloop.plan_next import Advancing, NextRequest, advance
from taskloop.plan_ops import Adoption, Failed, Quiet, Reads, Round, Starting, require_database
from taskloop.plan_publish import PlanPublish
from taskloop.plan_reads import SlotUse
from taskloop.plan_release import PlanRelease
from taskloop.plan_repeat import PlanRepeat
from taskloop.plan_rounds import Pacing, inputs
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore, StoreUnavailable
from taskloop.plan_types import Checkouts
from taskloop.plan_verifier import PlanVerifier
from taskloop.rounds_lock import RoundsLockUnavailable, RoundsRunning, hold
from taskloop.slot_lock import refused, repeating
from taskloop.task import TaskInspectionError


def load_config(config: str | None, flags: Flags, home: Callable[[], Path] = Path.home) -> Loaded | ConfigRefused:
    """Read the machine config: `--config FILE` must exist (else `missing`); the fixed file under home may be absent (all
    defaults). Unreadable is refused. No environment variable is read here; `Path.home()` itself reads `HOME`."""
    base = home()
    path = config_file(base) if config is None else Path(config).absolute()
    try:
        text: str | None = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if config is not None:
            return ConfigRefused("missing", detail=f"No config file at {path}")
        text = None
    except UnicodeError as error:
        return ConfigRefused("toml", detail=str(error))
    except OSError as error:
        return ConfigRefused("unreadable", detail=f"{type(error).__name__}: {path}")
    settings = resolve(text, flags, base)
    return settings if isinstance(settings, ConfigRefused) else Loaded(path, text is not None, settings)


@contextmanager
def _read_only(database: Path) -> Generator[sqlite3.Connection | Failed]:
    found = require_database(lambda: Store(SCHEMA).open_ro(database))
    try:
        yield found
    finally:
        if isinstance(found, sqlite3.Connection):
            found.close()


def _reader(con: sqlite3.Connection) -> PlanStore:
    return PlanStore(lambda: con)


@contextmanager
def open_plan_reads(database: Path) -> Generator[Reads | Failed]:
    """Read-only factory.db, the native process-table observation, the wall clock and the read-only leftovers of a stage
    still to settle (Git and slot reads); writes and creates nothing."""
    with _read_only(database) as con:
        if isinstance(con, Failed):
            yield con
        else:
            reader = _reader(con)
            verifier = PlanVerifier(reader, checkouts, RealSlotFiles(), worker_gone, time.time, refused)  # never verifies
            yield Reads(reader, entry_seen, time.time, verifier.leftovers)


@contextmanager
def open_plan_start(database: Path, artifacts: Path) -> Generator[Starting | Failed]:
    """The database guard first, then the admission, the launcher and the repeat (with the verifier's shared writer, which
    this closes) on the same paths."""
    store = Store(SCHEMA)
    with _read_only(database) as con:
        try:
            if isinstance(con, Failed):
                yield con
            else:
                yield _starting(_reader(con), database, artifacts, store)
        finally:
            store.close_shared()


def _starting(reader: PlanStore, database: Path, artifacts: Path, store: Store) -> Starting:
    admission, launcher = open_plan_admission(database, artifacts), open_launcher(database, artifacts)
    repeat = PlanRepeat(reader, open_plan_verifier(database, store), PlanFiles(artifacts), admission, launcher, worker_gone, entry_seen,
                        time.time, repeating)
    return Starting(reader, admission, launcher, time.time, repeat)


@contextmanager
def open_plan_next(database: Path, artifacts: Path, tracker_root: str) -> Generator[Advancing | Failed]:
    """`tl plan next`: the database guard first, then the tracker's read port at the explicit root (an unusable root
    refuses `tracker_root`), the start, verify, release and publish ports on one shared writer (closed here), the reads
    and the round log appended under the artifacts root."""
    store = Store(SCHEMA)
    with _read_only(database) as con:
        try:
            if isinstance(con, Failed):
                yield con
                return
            try:
                ready = tracker_reads(tracker_root)
            except TaskInspectionError as error:
                yield Failed("refused", "tracker_root", str(error))
                return
            reader = _reader(con)
            reads = Reads(reader, entry_seen, time.time, PlanVerifier(reader, checkouts, RealSlotFiles(), worker_gone, time.time,
                                                                       refused).leftovers)
            yield Advancing(reads, _starting(reader, database, artifacts, store), open_plan_verifier(database, store),
                            open_releaser(database, store), open_publisher(database, store), ready, PlanFiles(artifacts).log_round)
        finally:
            store.close_shared()


def one_round(database: Path, artifacts: Path, request: NextRequest, stopping: Callable[[], bool]) -> Callable[[Quiet], Round | Failed]:
    """One `tl plan rounds` round: `open_plan_next`'s fresh ports, its `stopping` the rounds process's flag. A factory.db
    that exists but cannot be opened now (locked, busy) is `unavailable:store`, so the rounds back off; an absent one stays
    `refused:database` (a deliberate discard ends the rounds)."""

    def once(quiet: Quiet) -> Round | Failed:
        with open_plan_next(database, artifacts, request.tracker_root) as ports:
            if isinstance(ports, Failed):
                return _transient(ports, database)
            return advance(replace(ports, stopping=stopping), replace(request, quiet=quiet))

    return once


def _transient(refused: Failed, database: Path) -> Failed:
    if refused.reason == "database" and database.exists():
        return Failed("unavailable", "store", "factory.db exists but could not be opened now")
    return refused


def _slot_use(database: Path) -> Callable[[], SlotUse | None]:
    """The check between rounds: a read-only open per call, None when factory.db or the read fails."""

    def read() -> SlotUse | None:
        with _read_only(database) as con:
            if isinstance(con, Failed):
                return None
            try:
                return _reader(con).slot_use()
            except StoreUnavailable:
                return None

    return read


def _unlogged(artifacts: Path) -> Callable[[], None]:
    def warn() -> None:
        print(f"Log: not written ({artifacts / 'rounds.log'})", file=sys.stderr)

    return warn


def _say(text: str) -> None:
    os.write(2, (text + "\n").encode())  # unbuffered: the SIGINT handler may say it while the process writes stderr


def _rounds_lock(database: Path, request: NextRequest) -> Callable[[], None] | Failed:
    """The inputs, the database guard, then the backlog's rounds lock (its release), in that order."""
    found = inputs(request)
    if found is None:
        with _read_only(database) as con:
            found = con if isinstance(con, Failed) else None
    if found is not None:
        return found
    try:
        return hold(database, request.backlog).release
    except RoundsRunning as error:
        return Failed("refused", "rounds_running", str(error))
    except RoundsLockUnavailable as error:
        return Failed("refused", "rounds_lock", f"{error}: the rounds lock beside {database}")


@contextmanager
def open_plan_rounds(database: Path, artifacts: Path, request: NextRequest) -> Generator[Pacing | Failed]:
    """`tl plan rounds`: refused before any round (inputs, `database`/`schema`, `rounds_running`), else the rounds lock and
    the SIGINT handler (`interrupts`) for the block's life, per-round `open_plan_next` ports, the wall and monotonic clocks,
    `time.sleep`, the round log and the `Log: not written` warning on stderr."""
    release = _rounds_lock(database, request)
    if isinstance(release, Failed):
        yield release
        return
    try:
        with installed(_say) as interrupts:
            yield Pacing(one_round(database, artifacts, request, interrupts.stopping), _slot_use(database), time.time, time.monotonic,
                         time.sleep, PlanFiles(artifacts).log_round, _unlogged(artifacts), interrupts.stopping, os.getpid())
    finally:
        release()


@contextmanager
def open_plan_verify(database: Path) -> Generator[tuple[PlanStore, PlanVerifier, PlanRelease, PlanPublish] | Failed]:
    """The database guard first, then the verifier's, the releaser's and the publisher's shared writer: no empty factory.db
    is ever created."""
    store = Store(SCHEMA)
    with _read_only(database) as con:
        try:
            if isinstance(con, Failed):
                yield con
            else:
                yield _reader(con), open_plan_verifier(database, store), open_releaser(database, store), open_publisher(database, store)
        finally:
            store.close_shared()


@contextmanager
def open_plan_publish(database: Path) -> Generator[tuple[PlanStore, PlanPublish] | Failed]:
    """The database guard first, then the publisher's shared writer (`tl plan publish`)."""
    store = Store(SCHEMA)
    with _read_only(database) as con:
        try:
            yield con if isinstance(con, Failed) else (_reader(con), open_publisher(database, store))
        finally:
            store.close_shared()


@contextmanager
def open_plan_release(database: Path) -> Generator[tuple[PlanStore, PlanRelease] | Failed]:
    """The database guard first, then the releaser's shared writer (`tl plan release`)."""
    store = Store(SCHEMA)
    with _read_only(database) as con:
        try:
            yield con if isinstance(con, Failed) else (_reader(con), open_releaser(database, store))
        finally:
            store.close_shared()


def adopt(database: Path, checkout: Path, root: Path, count: int, repos: Checkouts = checkouts) -> Adoption | Failed:
    """The only command that creates factory.db, and only after the checkout is a repository and an existing factory.db
    is this schema: a missing or non-repository checkout refuses `checkout`, another schema `schema`; nothing is made."""
    path = checkout.expanduser().absolute()
    if not path.is_dir():
        return Failed("refused", "checkout", f"No checkout directory at {path}")
    try:
        repos(path.resolve()).identity()
    except NotARepo as error:
        return Failed("refused", "checkout", str(error))
    except GitUnavailable as error:
        return Failed("unavailable", "git", str(error))
    if database.exists():
        with _read_only(database) as con:
            if isinstance(con, Failed):
                return con
    database.parent.mkdir(parents=True, exist_ok=True)
    return Adoption(adopt_slots(database, path, root, count, repos))
