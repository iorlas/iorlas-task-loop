"""The registered entry process of one admitted plan attempt: `python -I -m taskloop.attempt_entry DB ARTIFACTS BACKLOG TASK`.

It runs only as the identity the launcher registered: its own boot-aware identity is read and compared with the stored
entry before the attempt key is used or any credential is read. It never creates factory.db, runs the agent at most once
(through `PlanAttempts.execute`), retries only an unavailable publication, then verifies once (`PlanVerifier.verify`:
commit the listed paths, check the tree is clean, judge; never retried), and writes one log line of fixed words: status
and reason, read back after a stored verdict (a published retry instead keeps the run's own words and adds `publish=` and
the collected `then=`), always `verify=`, then `claim=` (the tracker claim's lease, renewed by `claim_lease` while the
step runs), never facts, environment, argv or exception text. A claim found lost before the agent starts refuses
(`refused claim_lost`); one lost later is only recorded. It exits 0 only for a verified plan, new or reused
(`plan.succeeded`). Its stdout and stderr are the attempt's `entry.log`.
"""

import os
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlite_store import open_ro
from stream_proc import ProcessObservation, inspect_process

from taskloop.claim_lease import HeartbeatFor, KeepAlive, Stop, keeping
from taskloop.composition import open_plan_attempts, tracker_claims, tracker_located, worker_gone
from taskloop.plan import ACCEPTED, PlanAttempts, judged, succeeded
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import StoreUnavailable
from taskloop.plan_types import (
    AttemptKey,
    AttemptResult,
    NotApplicable,
    PublicationResult,
    Rejected,
    Unsettled,
    Verified,
    VerifyRefused,
    VerifyResult,
    VerifyUnavailable,
    WorkerGone,
)
from taskloop.plan_verifier import PlanVerifier

PUBLISH_RETRIES = 3
RETRY_WAIT = 2.0


@dataclass(frozen=True)
class _Registered:
    app: PlanAttempts
    key: AttemptKey
    me: tuple[int, str, str]
    tracker_root: str


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


def shown(result: VerifyResult) -> str:
    """The `verify=` word of the log line."""
    match result:
        case Verified() | Rejected():
            return judged(result)
        case Unsettled(reason=reason):
            return "unsettled:" + reason
        case VerifyUnavailable(reason=reason):
            return "unavailable:" + reason
        case VerifyRefused(reason=reason):
            return "refused:" + reason
        case NotApplicable():
            return "not_applicable"


def _registered(
    args: EntryArgs, attempts: Callable[[Path, Path], PlanAttempts], inspect: Callable[[int], ProcessObservation]
) -> _Registered | str:
    """The attempt this process is the registered entry of, with its tracker root; otherwise the refusal's log words."""
    try:
        if not _exists(args.database):
            return "refused database"
        app = attempts(args.database, args.artifacts)
        seen = inspect(os.getpid())
        found = app.store.attempt_of(args.backlog, args.task_id)
        tracker = None if found is None else app.store.tracker_root(found[0])
    except (sqlite3.Error, StoreUnavailable):
        return "unavailable store"
    if found is None or tracker is None:
        return "refused absent"
    key, _phase, entry = found
    me = None if seen.kind != "matching" or seen.identity is None else (seen.identity.pid, seen.identity.start, seen.identity.boot)
    if me is None or me != entry:
        return "refused identity"
    return _Registered(app, key, me, tracker)


def _step(found: _Registered, clock: Callable[[], float], wait: Callable[[float], None], gone: WorkerGone) -> tuple[str, bool]:
    """Execute once, retry an unavailable publication, verify once: the log words and whether the plan succeeded."""
    app, key = found.app, found.key
    result = app.execute(key, found.me)
    published = _publish(app, result, clock, wait)
    accepted = published is not None and published.status in ACCEPTED
    verified = PlanVerifier(app.store, app.checkouts, app.slot_files, gone, app.clock).verify(key)
    # newly stored facts or a stored verdict: read the terminal outcome back
    latest = app.collect(key) if accepted or isinstance(verified, (Verified, Rejected)) else result
    line = f"{latest.status} {latest.reason}"
    if published is not None:
        then = f" then={latest.status}:{latest.reason}" if accepted else ""
        line = f"{result.status} {result.reason} publish={published.status}{then}"
    return f"{line} verify={shown(verified)}", succeeded(latest)


def enter(
    args: EntryArgs,
    attempts: Callable[[Path, Path], PlanAttempts],
    inspect: Callable[[int], ProcessObservation],
    clock: Callable[[], float],
    wait: Callable[[float], None],
    log: Callable[[str], None],
    gone: WorkerGone,
    heartbeat_for: HeartbeatFor,
    stop: Stop,
) -> int:
    """Run the attempt as its registered entry; the return code is display only. `gone` observes the worker before the
    verification's Git write. The claim is renewed once before the agent (a lost claim refuses: never re-claimed), then
    by a thread until the step ends (`stop` ends it); a later loss or fault is only the log line's `claim=` word."""
    found = _registered(args, attempts, inspect)
    if isinstance(found, str):
        log(found)
        return 1
    alive = KeepAlive(heartbeat_for(found.tracker_root, args.task_id), stop, clock)
    alive.renew()
    if alive.word() == "lost":
        log("refused claim_lost")
        return 1
    with keeping(alive):
        line, ok = _step(found, clock, wait, gone)
    log(f"{line} claim={alive.word()}")
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    os.dup2(2, 1)  # stdout joins stderr, the attempt's entry.log; stdin is never read
    tracker_located()  # before any thread or bd call: the stored tracker root decides the tracker bd renews the claim at

    def log(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    try:
        args = arguments(sys.argv[1:] if argv is None else argv)
        if args is None:
            log("refused usage")
            return 2
        heartbeat_for = tracker_claims().heartbeat_for
        return enter(args, open_plan_attempts, inspect_process, time.time, time.sleep, log, worker_gone, heartbeat_for, threading.Event())
    except BaseException as error:  # the type name only, never its text
        log("failed " + type(error).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
