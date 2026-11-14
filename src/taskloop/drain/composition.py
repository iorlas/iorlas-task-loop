"""Drain composition: existing compatible SQLite only, owning readers and native process observations."""

import sqlite3
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from beads_client import BdError
from sqlite_store import SchemaError, Store

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import DEFAULT_GIT_READ_SECONDS
from taskloop.check_store import CheckStore
from taskloop.drain.drain import Ports
from taskloop.drain.models import Action, Conclusion, Owner, Result
from taskloop.drain.observe import observe
from taskloop.drain.reconcile import Reconcile
from taskloop.drain.store import DrainStore
from taskloop.factory_schema import SCHEMA, current, refusal
from taskloop.git_views import GitViews
from taskloop.land_store import LandStore
from taskloop.merge.store import MergeStore
from taskloop.setup_store import SetupStore
from taskloop.task import TaskInspectionError
from taskloop.tracker import ACTOR
from taskloop.tracker_client import inspect_tracker_task, tracker_claims


def _owners(attempts: AttemptStore) -> tuple[Owner, ...]:
    connect, begin = attempts.connect, attempts.begin
    return (attempts.drain_processes() + CheckStore(connect, begin).drain_processes()
            + SetupStore(connect, begin).drain_processes() + MergeStore(connect, begin).active_processes())


def _return_claim(action: Action) -> bool:
    try:
        task = inspect_tracker_task(action.subject, action.backlog, action.tracker_root)
        if task.assignee == ACTOR and task.status == "in_progress":
            tracker_claims().unclaim(action.tracker_root, action.subject)
            task = inspect_tracker_task(action.subject, action.backlog, action.tracker_root)
        return task.assignee != ACTOR or task.status != "in_progress"
    except BdError, TaskInspectionError:
        return False


@contextmanager
def open_drain(database: Path, report: Callable[[Result], None] = lambda _result: None) -> Generator[Ports | Result]:
    """Validate read-only first, then open mode=rw (never SQLite's creating mode). No filesystem initialization."""
    reader = writer = None
    opened: Ports | Result
    try:
        reader = Store(SCHEMA).open_ro(database)
        if reader is None:
            try:
                database.stat()
            except FileNotFoundError:
                opened = Result(conclusion=Conclusion.REFUSED, detail=f"There is no existing factory database at {database}.")
            else:
                opened = Result(
                    conclusion=Conclusion.UNAVAILABLE,
                    detail=f"The existing factory database at {database} could not be read. Idle was not verified.",
                )
        else:
            writer = sqlite3.connect(database.absolute().as_uri() + "?mode=rw", uri=True, isolation_level=None)
            if not current(writer):
                raise sqlite3.DatabaseError("The database changed after its compatibility check")
            attempts = AttemptStore(lambda: writer)
            reconcile = Reconcile(
                attempts,
                LandStore(lambda: writer),
                GitViews(DEFAULT_GIT_READ_SECONDS).remotes,
                inspect_tracker_task,
                _return_claim,
                time.time,
            )
            opened = Ports(DrainStore(lambda: writer), lambda: _owners(attempts), observe, reconcile, time.sleep, report)
    except SchemaError as error:
        opened = Result(conclusion=Conclusion.REFUSED, detail=refusal(error, database))
    except (sqlite3.Error, OSError, StoreUnavailable) as error:
        opened = Result(
            conclusion=Conclusion.UNAVAILABLE,
            detail=f"Idle could not be verified: the factory database is unavailable ({type(error).__name__}).",
        )
    try:
        yield opened
    finally:
        for con in (reader, writer):
            if con is not None:
                con.close()
