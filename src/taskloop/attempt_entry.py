"""The registered entry process of one admitted plan attempt: `python -I -m taskloop.attempt_entry DB ARTIFACTS BACKLOG TASK`.

It runs only as the identity the launcher registered: its own boot-aware identity is read and compared with the stored
entry before the attempt key is used or any credential is read. It then holds its slot's custody lock (`slot_lock`)
until it exits; a held lock refuses (`refused slot_busy`) with nothing read or written. It never creates factory.db,
runs the agent at most once (through `Attempts.execute`), retries only an unavailable publication, then verifies
once (`Verifier.verify`: commit the listed paths, check the tree is clean, judge; never retried), and writes one log
line of fixed words: status and reason, read back after a stored verdict (a published retry instead keeps the run's
own words and adds `publish=` and the collected `then=`), always `verify=`, then `claim=` (the tracker claim's lease,
renewed by `claim_lease` while the step runs), then, once the result read back is collected, `release=` (the settled
release of its own slot, still under its lock: `released`, or why the slot stays held), then, for a verified plan only,
`branch=` (the publication of `task/<id>` to origin, once, after the lock is released: `published`, or the refusal or
unknown word; never retried here), never facts, environment, argv or exception text. A claim found lost before the agent
starts refuses (`refused claim_lost`); one lost later is only recorded. It exits 0 only for a verified plan, new or
reused (`plan.succeeded`), whatever its publication says. Its stdout and stderr are the attempt's `entry.log`.
"""

import os
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from git_porcelain import GitUnavailable
from sqlite_store import open_ro
from stream_proc import ProcessObservation, inspect_process

from taskloop import slot_lock
from taskloop.admit import Unclaim
from taskloop.attempt import ACCEPTED, Attempts, judged, succeeded
from taskloop.attempt_store import StoreRefused, StoreUnavailable
from taskloop.attempt_types import (
    Admission,
    AttemptKey,
    AttemptRecord,
    AttemptResult,
    Checkouts,
    EntryIdentity,
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
from taskloop.claim_lease import HeartbeatFor, KeepAlive, Stop, keeping
from taskloop.composition import entry_seen, open_attempts, remotes, tracker_claims, tracker_located, worker_gone
from taskloop.factory_schema import SCHEMA
from taskloop.publish import BranchPublish, publish_word
from taskloop.slot_release import SlotRelease, release_word
from taskloop.verifier import Verifier

PUBLISH_RETRIES = 3
RETRY_WAIT = 2.0


@dataclass(frozen=True)
class _Registered:
    app: Attempts
    key: AttemptKey
    me: EntryIdentity
    tracker_root: str
    cwd: str  # the slot, from the stored reservation: its custody lock is beside it


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
    app: Attempts, result: AttemptResult, clock: Callable[[], float], wait: Callable[[float], None]
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
    args: EntryArgs, attempts: Callable[[Path, Path], Attempts], inspect: Callable[[int], ProcessObservation]
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
    record = _record(app, key)
    return record if isinstance(record, str) else _Registered(app, key, me, tracker, record.admission.cwd)


def _record(app: Attempts, key: AttemptKey) -> AttemptRecord | str:
    """One fenced load (the held reservation) for the attempt's slot path, else the refusal's log words."""
    try:
        record = app.store.load(key)
    except (sqlite3.Error, StoreUnavailable):
        return "unavailable store"
    except StoreRefused as error:
        return f"refused {error}"
    return "refused absent" if record is None else record


def _held(_admission: Admission) -> AbstractContextManager[None]:
    """The entry's verify runs inside the slot lock the entry already holds: the library's nonreentrant lock would refuse
    a second acquire in this process."""
    return nullcontext()


def _unheld(_cwd: str, _attempt_id: str) -> AbstractContextManager[None]:
    """The entry's release runs inside the slot lock the entry already holds."""
    return nullcontext()


def _step(found: _Registered, clock: Callable[[], float], wait: Callable[[float], None], gone: WorkerGone) -> tuple[str, bool, bool]:
    """Execute once, retry an unavailable publication, verify once: the log words, whether the plan succeeded and whether
    the result read back is collected (terminal)."""
    app, key = found.app, found.key
    result = app.execute(key, found.me)
    published = _publish(app, result, clock, wait)
    accepted = published is not None and published.status in ACCEPTED
    verified = Verifier(app.store, app.checkouts, app.slot_files, gone, app.clock, _held).verify(key)
    # newly stored facts or a stored verdict: read the terminal outcome back
    latest = app.collect(key) if accepted or isinstance(verified, (Verified, Rejected)) else result
    line = f"{latest.status} {latest.reason}"
    if published is not None:
        then = f" then={latest.status}:{latest.reason}" if accepted else ""
        line = f"{result.status} {result.reason} publish={published.status}{then}"
    return f"{line} verify={shown(verified)}", succeeded(latest), latest.status == "collected"


def enter(
    args: EntryArgs,
    attempts: Callable[[Path, Path], Attempts],
    inspect: Callable[[int], ProcessObservation],
    clock: Callable[[], float],
    wait: Callable[[float], None],
    log: Callable[[str], None],
    gone: WorkerGone,
    heartbeat_for: HeartbeatFor,
    stop: Stop,
    unclaim: Unclaim,
    publishing: Checkouts,
) -> int:
    """Run the attempt as its registered entry; the return code is display only. After the identity check the entry
    takes its slot's custody lock (`slot_lock`, never waiting: `refused slot_busy`, or `refused lock`) and holds it
    around everything else: preparation, the agent, the publish retries and the verify, whose own hold is a no-op.
    `gone` observes the worker before the verification's Git write. The claim is renewed once before the agent (a lost
    claim refuses: never re-claimed), then by a thread until the step ends (`stop` ends it); a later loss or fault is
    only the log line's `claim=` word. A collected step then releases its own slot, settled (`unclaim` is the release's
    port; a settled release never calls it). A verified plan is then published once, after the lock is released and the
keep-alive stopped, through `publishing` (the remote-capable Git views); the push never pins the slot."""
    found = _registered(args, attempts, inspect)
    if isinstance(found, str):
        log(found)
        return 1
    try:
        lock = slot_lock.acquire(found.cwd, found.key.attempt_id, "entry")
    except slot_lock.SlotBusy:
        log("refused slot_busy")
        return 1
    except slot_lock.SlotLockUnavailable:
        log("refused lock")
        return 1
    try:  # the lock is outermost: the claim's keep-alive starts and stops inside it
        alive = KeepAlive(heartbeat_for(found.tracker_root, args.task_id), stop, clock)
        line, ok = _claimed(found, clock, wait, gone, alive, unclaim)
    finally:
        lock.release()
    if ok:  # outside the lock: the push reads only committed objects and writes only refs
        line += " branch=" + _branch(found, publishing)
    log(line)
    return 0 if ok else 1


def _branch(found: _Registered, publishing: Checkouts) -> str:
    """The publication's word, once. A failure `publish` does not map itself (a Git view that cannot be opened, a file
    read) is `unavailable:git` or `unavailable:store`: it never loses the step's log line or a verified plan's exit 0."""
    app = found.app
    try:
        return publish_word(BranchPublish(app.store, publishing, app.slot_files, app.clock).publish(found.key))
    except (GitUnavailable, ValueError, OSError):
        return "unavailable:git"
    except (sqlite3.Error, StoreUnavailable):
        return "unavailable:store"


def _claimed(
    found: _Registered,
    clock: Callable[[], float],
    wait: Callable[[float], None],
    gone: WorkerGone,
    alive: KeepAlive,
    unclaim: Unclaim,
) -> tuple[str, bool]:
    """The step under the slot's lock, with the claim renewed before the agent and kept alive while it runs; a collected
    step's slot is then released (settled: parked when clean, the claim kept), still under the lock. The log line so far
    and whether the plan was verified."""
    alive.renew()
    if alive.word() == "lost":
        return "refused claim_lost", False
    with keeping(alive):
        line, ok, collected = _step(found, clock, wait, gone)
    line = f"{line} claim={alive.word()}"
    if collected:
        app = found.app
        releaser = SlotRelease(app.store, app.checkouts, app.slot_files, entry_seen, gone, _unheld, unclaim, app.clock)
        line += " release=" + release_word(releaser.release(found.key, False, found.me))
    return line, ok


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
        claims = tracker_claims()
        return enter(args, open_attempts, inspect_process, time.time, time.sleep, log, worker_gone, claims.heartbeat_for,
                     threading.Event(), claims.unclaim, remotes)
    except BaseException as error:  # the type name only, never its text
        log("failed " + type(error).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
