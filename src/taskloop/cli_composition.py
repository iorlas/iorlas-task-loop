"""Construct the command surface's boundaries: the machine config file, the read-only factory.db guard, and the plan and
slot openers over `composition`'s real wiring. The attempt entry process never imports this module (.importlinter)."""

import sqlite3
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
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
from taskloop.machine_config import ConfigRefused, Flags, Loaded, config_file, resolve
from taskloop.plan_files import PlanFiles
from taskloop.plan_next import Advancing
from taskloop.plan_ops import Adoption, Failed, Reads, Starting, require_database
from taskloop.plan_publish import PlanPublish
from taskloop.plan_release import PlanRelease
from taskloop.plan_repeat import PlanRepeat
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore
from taskloop.plan_types import Checkouts
from taskloop.plan_verifier import PlanVerifier
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
