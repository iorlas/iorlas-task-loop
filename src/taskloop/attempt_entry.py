"""The registered entry process of one admitted plan attempt: `python -I -m taskloop.attempt_entry DB ARTIFACTS BACKLOG TASK`.

It runs only as the identity the launcher registered: its own boot-aware identity is read and compared with the stored
entry before the attempt key is used or any credential is read. It never creates factory.db, runs the agent at most once
(through `PlanAttempts.execute`), retries only an unavailable publication, and writes one log line: status and reason,
never facts, environment, argv or exception text. Its stdout and stderr are the attempt's `entry.log`.
"""

import os
import sqlite3
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlite_store import open_ro
from stream_proc import ProcessObservation, inspect_process

from taskloop.composition import open_plan_attempts
from taskloop.plan import PlanAttempts
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import StoreUnavailable
from taskloop.plan_types import AttemptResult, PublicationResult

PUBLISH_RETRIES = 3
RETRY_WAIT = 2.0


@dataclass(frozen=True)
class EntryArgs:
    database: Path
    artifacts: Path
    backlog: str
    task_id: str


def arguments(argv: Sequence[str]) -> EntryArgs | None:
    """Two absolute paths, a backlog and a task id; anything else is refused."""
    if len(argv) != 4 or not all(argv):
        return None
    database, artifacts = Path(argv[0]), Path(argv[1])
    if not (database.is_absolute() and artifacts.is_absolute()):
        return None
    return EntryArgs(database, artifacts, argv[2], argv[3])


def _exists(database: Path) -> bool:
    """factory.db is opened read-only first, so a missing file is refused, never created."""
    con = open_ro(database, SCHEMA)
    if con is None:
        return False
    con.close()
    return True


def _publish(
    app: PlanAttempts, result: AttemptResult, clock: Callable[[], float], wait: Callable[[float], None]
) -> PublicationResult | None:
    """Retry an unfinished publication only while it is unavailable: at most PUBLISH_RETRIES, never past the deadline."""
    pending, published = result.pending, None
    if pending is None or result.status != "unavailable":  # a conflict is never retried
        return None
    for _ in range(PUBLISH_RETRIES):
        wait(RETRY_WAIT)
        if clock() >= pending.admission.deadline:
            break
        published = app.publish(pending)
        if published.status != "unavailable":
            break
    return published


def enter(
    args: EntryArgs,
    attempts: Callable[[Path, Path], PlanAttempts],
    inspect: Callable[[int], ProcessObservation],
    clock: Callable[[], float],
    wait: Callable[[float], None],
    log: Callable[[str], None],
) -> int:
    """Run the attempt as its registered entry; the return code is display only."""
    try:
        if not _exists(args.database):
            log("refused database")
            return 1
        app = attempts(args.database, args.artifacts)
        seen = inspect(os.getpid())
        found = app.store.attempt_of(args.backlog, args.task_id)
    except (sqlite3.Error, StoreUnavailable):
        log("unavailable store")
        return 1
    if found is None:
        log("refused absent")
        return 1
    key, _phase, entry = found
    me = None if seen.kind != "matching" or seen.identity is None else (seen.identity.pid, seen.identity.start, seen.identity.boot)
    if me is None or me != entry:
        log("refused identity")
        return 1
    result = app.execute(key, me)
    published = _publish(app, result, clock, wait)
    line = f"{result.status} {result.reason}".rstrip()
    log(line if published is None else f"{line} publish={published.status}")
    return 0 if result.status == "collected" or (published is not None and published.status in ("accepted", "already_same")) else 1


def main(argv: Sequence[str] | None = None) -> int:
    os.dup2(2, 1)  # stdout joins stderr, the attempt's entry.log; stdin is never read

    def log(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    try:
        args = arguments(sys.argv[1:] if argv is None else argv)
        if args is None:
            log("refused usage")
            return 2
        return enter(args, open_plan_attempts, inspect_process, time.time, time.sleep, log)
    except BaseException as error:  # the type name only, never its text
        log("failed " + type(error).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
