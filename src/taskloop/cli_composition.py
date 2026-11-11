"""Construct the command surface's boundaries: the machine config file, the read-only factory.db guard, and the step and
slot openers over `composition`'s real wiring. The attempt entry process never imports this module (.importlinter)."""

import os
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from git_porcelain import GitUnavailable, NotARepo
from sqlite_store import Store

from taskloop.attempt_reads import SlotUse
from taskloop.attempt_status import StatusPorts
from taskloop.attempt_store import AttemptStore, StoreUnavailable
from taskloop.check_release import ChecksRelease
from taskloop.composition import (
    adopt_slots,
    open_admission,
    open_advance,
    open_chain,
    open_checking,
    open_checks_admission,
    open_checks_launcher,
    open_checks_releaser,
    open_launcher,
    open_publisher,
    open_releaser,
    open_verifier,
    real_slots,
)
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitProfileFiles, checkouts, remotes
from taskloop.interrupts import installed
from taskloop.land_check import LandPorts
from taskloop.land_store import LandStore
from taskloop.machine_config import ConfigRefused, Flags, Loaded, config_file, resolve
from taskloop.operations import Adoption, ChecksPorts, Failed, Quiet, Round, StartPorts, require_database
from taskloop.owned_processes import current_boot, entry_seen, setup_seen, this_process, worker_gone
from taskloop.publish import BranchPublish
from taskloop.repeat import StepRepeat
from taskloop.round import NextRequest, RoundPorts, run_round
from taskloop.rounds import RoundsPorts, inputs
from taskloop.rounds_lock import RoundsLockUnavailable, RoundsRunning, hold
from taskloop.slot_files import RealSlotFiles
from taskloop.slot_lock import landing, probe, refused, repeating
from taskloop.slot_release import SlotRelease
from taskloop.slots import SlotGit
from taskloop.task import TaskInspectionError
from taskloop.tracker_client import inspect_tracker_task, tracker_claims, tracker_reads
from taskloop.verifier import Verifier


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


def _reader(con: sqlite3.Connection) -> AttemptStore:
    return AttemptStore(lambda: con)


@contextmanager
def open_reads(database: Path) -> Generator[StatusPorts | Failed]:
    """Read-only factory.db, the native process-table observation, the wall clock and the read-only leftovers of a step
    still to settle (Git and slot reads); writes and creates nothing."""
    with _read_only(database) as con:
        if isinstance(con, Failed):
            yield con
        else:
            reader = _reader(con)
            verifier = Verifier(reader, checkouts, RealSlotFiles(), worker_gone, time.time, refused)  # never verifies
            yield StatusPorts(reader, entry_seen, time.time, verifier.leftovers, current_boot, setup_seen)


@contextmanager
def open_start(database: Path, artifacts: Path) -> Generator[StartPorts | Failed]:
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


def _starting(reader: AttemptStore, database: Path, artifacts: Path, store: Store) -> StartPorts:
    admission, launcher, chain = open_admission(database, artifacts), open_launcher(database, artifacts), open_chain(database, artifacts)
    repeat = StepRepeat(reader, open_verifier(database, store), EvidenceFiles(artifacts), chain, launcher, worker_gone, entry_seen,
                        time.time, repeating)
    releaser = open_checks_releaser(database, store)
    checks = ChecksPorts(open_checks_admission(database), open_checks_launcher(database, artifacts), releaser)
    return StartPorts(reader, admission, launcher, time.time, repeat, open_advance(database, artifacts), checks)


@contextmanager
def open_next(database: Path, artifacts: Path, tracker_root: str) -> Generator[RoundPorts | Failed]:
    """`tl step next`: the database guard first, then the tracker's read port at the explicit root (an unusable root
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
            leftovers = Verifier(reader, checkouts, RealSlotFiles(), worker_gone, time.time, refused).leftovers
            reads = StatusPorts(reader, entry_seen, time.time, leftovers, current_boot, setup_seen)
            yield RoundPorts(reads, _starting(reader, database, artifacts, store), open_verifier(database, store),
                            open_releaser(database, store), open_publisher(database, store), ready, EvidenceFiles(artifacts).log_round)
        finally:
            store.close_shared()


def one_round(database: Path, artifacts: Path, request: NextRequest, stopping: Callable[[], bool]) -> Callable[[Quiet], Round | Failed]:
    """One `tl step rounds` round: `open_next`'s fresh ports, its `stopping` the rounds process's flag. A factory.db
    that exists but cannot be opened now (locked, busy) is `unavailable:store`, so the rounds back off; an absent one stays
    `refused:database` (a deliberate discard ends the rounds)."""

    def once(quiet: Quiet) -> Round | Failed:
        with open_next(database, artifacts, request.tracker_root) as ports:
            if isinstance(ports, Failed):
                return _transient(ports, database)
            return run_round(replace(ports, stopping=stopping), replace(request, quiet=quiet))

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
def open_rounds(database: Path, artifacts: Path, request: NextRequest) -> Generator[RoundsPorts | Failed]:
    """`tl step rounds`: refused before any round (inputs, `database`/`schema`, `rounds_running`), else the rounds lock and
    the SIGINT handler (`interrupts`) for the block's life, per-round `open_next` ports, the wall and monotonic clocks,
    `time.sleep`, the round log and the `Log: not written` warning on stderr."""
    release = _rounds_lock(database, request)
    if isinstance(release, Failed):
        yield release
        return
    try:
        with installed(_say) as interrupts:
            yield RoundsPorts(one_round(database, artifacts, request, interrupts.stopping), _slot_use(database), time.time, time.monotonic,
                         time.sleep, EvidenceFiles(artifacts).log_round, _unlogged(artifacts), interrupts.stopping, os.getpid())
    finally:
        release()


@contextmanager
def open_verify(database: Path) -> Generator[tuple[AttemptStore, Verifier, SlotRelease, BranchPublish] | Failed]:
    """The database guard first, then the verifier's, the releaser's and the publisher's shared writer: no empty factory.db
    is ever created."""
    store = Store(SCHEMA)
    with _read_only(database) as con:
        try:
            if isinstance(con, Failed):
                yield con
            else:
                yield _reader(con), open_verifier(database, store), open_releaser(database, store), open_publisher(database, store)
        finally:
            store.close_shared()


@contextmanager
def open_publish(database: Path) -> Generator[tuple[AttemptStore, BranchPublish] | Failed]:
    """The database guard first, then the publisher's shared writer (`tl step publish`)."""
    store = Store(SCHEMA)
    with _read_only(database) as con:
        try:
            yield con if isinstance(con, Failed) else (_reader(con), open_publisher(database, store))
        finally:
            store.close_shared()


@contextmanager
def open_release(database: Path) -> Generator[tuple[AttemptStore, SlotRelease, ChecksRelease] | Failed]:
    """The database guard first, then the releasers' shared writer (`tl step release`: the agent attempt's and the
    checks attempt's)."""
    store = Store(SCHEMA)
    with _read_only(database) as con:
        try:
            yield con if isinstance(con, Failed) else (_reader(con), open_releaser(database, store), open_checks_releaser(database, store))
        finally:
            store.close_shared()


def adopt(database: Path, checkout: Path, root: Path, count: int, git: SlotGit | None = None) -> Adoption | Failed:
    """The only command that creates factory.db, and only after the checkout is a repository and an existing factory.db
    is this schema: a missing or non-repository checkout refuses `checkout`, another schema `schema`; nothing is made.
    `git` defaults to real Git and the real slot file port (`real_slots`)."""
    path, git = checkout.expanduser().absolute(), git or real_slots()
    if not path.is_dir():
        return Failed("refused", "checkout", f"No checkout directory at {path}")
    try:
        git.checkouts(path.resolve()).identity()
    except NotARepo as error:
        return Failed("refused", "checkout", str(error))
    except GitUnavailable as error:
        return Failed("unavailable", "git", str(error))
    if database.exists():
        with _read_only(database) as con:
            if isinstance(con, Failed):
                return con
    database.parent.mkdir(parents=True, exist_ok=True)
    return Adoption(adopt_slots(database, path, root, count, git))


def _land_profiles(checkout: Path) -> GitProfileFiles:
    """The target profile at O, read from Git objects on the person's checkout through the remote-capable view."""
    return GitProfileFiles(checkout, remotes)


@contextmanager
def open_land(database: Path, artifacts: Path) -> Generator[LandPorts | Failed]:
    """`tl step land` (tl-8bh9.14.8): the database guard first, then the land's ports over `composition.open_checking`'s
    real wiring (the validation's), the candidates' store on its connections, the person's checkout through the
    remote-capable view (`remotes`: hooks off, bounded transport, the person's credentials), the tracker read and claim
    heartbeat, a new stop event per keep-alive, this process's identity, the slot lock's probe and custody (`landing`),
    and this process's environment. Here, never in `composition`: neither entry may import the land
    (`rounds-never-land`)."""
    with _read_only(database) as con:
        if isinstance(con, Failed):
            yield con
            return
        work = open_checking(database, artifacts)
        yield LandPorts(work, LandStore(work.store.connect, work.store.begin), remotes, _land_profiles, inspect_tracker_task,
                        tracker_claims().heartbeat_for, threading.Event, this_process, probe, landing, os.environ)
