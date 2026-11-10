"""Construct the command surface's boundaries: the machine config file, the read-only factory.db guard, and the plan and
slot openers over `composition`'s real wiring. The attempt entry process never imports this module (.importlinter)."""

import sqlite3
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from git_porcelain import GitUnavailable, NotARepo
from sqlite_store import Store
from stream_proc import observe_owned

from taskloop.composition import (
    RealSlotFiles,
    adopt_slots,
    checkouts,
    open_launcher,
    open_plan_admission,
    open_plan_verifier,
    worker_gone,
)
from taskloop.machine_config import ConfigRefused, Flags, Loaded, config_file, resolve
from taskloop.plan_files import PlanFiles
from taskloop.plan_launch import Entry, entry_process
from taskloop.plan_ops import Adoption, Failed, Reads, Seen, Starting, require_database
from taskloop.plan_repeat import PlanRepeat
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore
from taskloop.plan_types import Checkouts
from taskloop.plan_verifier import PlanVerifier
from taskloop.slot_lock import refused


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


def entry_seen(entry: Entry) -> Seen:
    """A native process-table read of the registered entry, by the launcher's identity rule; no spawn or signal."""
    return observe_owned(entry_process(entry)).kind


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
                reader, admission, launcher = _reader(con), open_plan_admission(database, artifacts), open_launcher(database, artifacts)
                verifier = open_plan_verifier(database, store)
                repeat = PlanRepeat(reader, verifier, PlanFiles(artifacts), admission, launcher, worker_gone, entry_seen, time.time)
                yield Starting(reader, admission, launcher, time.time, repeat)
        finally:
            store.close_shared()


@contextmanager
def open_plan_verify(database: Path) -> Generator[tuple[PlanStore, PlanVerifier] | Failed]:
    """The database guard first, then the verifier's shared writer: no empty factory.db is ever created."""
    store = Store(SCHEMA)
    with _read_only(database) as con:
        try:
            yield con if isinstance(con, Failed) else (_reader(con), open_plan_verifier(database, store))
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
