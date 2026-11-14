"""The registered entry process of one admitted checks attempt: `python -I -m taskloop.check_entry DB ARTIFACTS BACKLOG
TASK` (tl-8bh9.14.6 section 6), launched by `launch.Launcher` over `CheckStore`. Its stdout and stderr are the checks
attempt's `entry.log`.

It runs only as the identity the launcher registered (`refused identity` otherwise), never creates factory.db, and
signals nothing. Order: its slot's custody lock (never waiting), held to the end; the claim renewed once (lost concludes
`claim_lost`, after the reconcile below marks gone unfinished results), then kept alive by a thread until the block ends
(a later loss is only the log's `claim=`); then the validation shared with the land (`validate.validate`, X with `main`
watched): the reconcile before any slot read or write (the latest setup run's unsettled command and every unsettled
result of the latest block, boot-aware: alive `unavailable checks:running`, unknown `checks:unknown`; gone, an unfinished
result becomes `interrupted`); the deadline (`expired`); the profile at X on the slot's pinned view
(`profile:<reason>`); `main` read (`main_moved`); a completed latest block is concluded as it stands, never run again; X
taken detached (`prepare.detach_at`); the slot reset to exactly X and set up at X (`environment.prepare_for`, no probe);
the block (`checks.Block`); `main` read again; the conclusion from the latest block; then the settled release of its own
slot under the lock it holds (`check_release`). Section 6.1 (`validate.concluded`): a condition the candidate caused, or
one a relaunch cannot clear, concludes `failed` with its reason and releases; an unavailable word, or a refusal in
`validate.RELAUNCHED`, leaves the attempt `admitted` and is counted (`CheckStore.refused`, whatever the word; two in a row
stop the rounds' relaunches), and so is any other fault once the attempt is the entry's own (`unavailable
fault:<type>`). One log line of fixed words: `collected passed|failed:<reason>` then `claim=` and `release=`, or the
refusal (then `claim=` once the claim was read). Exit 0 only for `passed`.
"""

import contextlib
import os
import sqlite3
import sys
import threading
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from stream_proc import ProcessObservation, inspect_process

from taskloop import slot_lock
from taskloop.attempt_entry import EntryArgs, arguments, database_exists
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptResult, EntryIdentity, entry_identity
from taskloop.check_release import ChecksRelease
from taskloop.check_store import ChecksRow
from taskloop.claim_lease import HeartbeatFor, KeepAlive, Stop, keeping, renewal
from taskloop.composition import Checking, open_checking
from taskloop.git_views import GitViews
from taskloop.slot_release import release_word
from taskloop.tracker_client import tracker_claims, tracker_located
from taskloop.validate import Ended, Target, Verdict, concluded, reconcile, validate


@dataclass(frozen=True)
class _Registered:
    work: Checking
    row: ChecksRow
    me: EntryIdentity
    slot_path: str  # the held reservation's slot: its custody lock is beside it


def _registered(
    args: EntryArgs, opened: Callable[[Path, Path], Checking], inspect: Callable[[int], ProcessObservation]
) -> _Registered | str:
    """The admitted checks attempt this process is the registered entry of, with its held slot; else the log words."""
    try:
        if not database_exists(args.database):
            return "refused database"
        work = opened(args.database, args.artifacts)
        seen = inspect(os.getpid())
        found = work.store.attempt_of(args.backlog, args.task_id)
        row = None if found is None else work.store.row(found[0])
        slot = None if found is None else work.store.slot_path(found[0])
    except (sqlite3.Error, StoreUnavailable):
        return "unavailable store"
    if found is None or row is None:
        return "refused absent"
    _key, state, entry = found
    me = None if seen.kind != "matching" or seen.identity is None else entry_identity(seen.identity)
    if me is None or me != entry:
        return "refused identity"
    if state != "admitted" or slot is None:
        return "refused " + (state if state != "admitted" else "stale_reservation")
    return _Registered(work, row, me, slot)


def _unheld(_slot_path: str, _attempt_id: str) -> AbstractContextManager[None]:
    """The entry's release runs inside the slot lock the entry already holds."""
    return nullcontext()


def _counted(found: _Registered, result: AttemptResult) -> str:
    """A relaunch: the refusal counted (a store that cannot count it changes nothing), its log words."""
    with contextlib.suppress(StoreRefused, StoreUnavailable):
        found.work.store.refused(found.row.key, result.reason)
    return f"{result.status} {result.reason}"


def enter(
    args: EntryArgs,
    opened: Callable[[Path, Path], Checking],
    inspect: Callable[[int], ProcessObservation],
    log: Callable[[str], None],
    heartbeat_for: HeartbeatFor,
    stop: Stop,
) -> int:
    """Run the checks attempt as its registered entry; the return code is display only."""
    found = _registered(args, opened, inspect)
    if isinstance(found, str):
        log(found)
        return 1
    try:
        lock = slot_lock.acquire(found.slot_path, found.row.key.attempt_id, "entry")
    except slot_lock.SlotBusy:
        log(_counted(found, AttemptResult("refused", "slot_busy")))
        return 1
    except slot_lock.SlotLockUnavailable:
        log(_counted(found, AttemptResult("refused", "lock")))
        return 1
    try:  # the lock is outermost: the claim's keep-alive starts and stops inside it
        alive = KeepAlive(heartbeat_for(found.row.tracker_root, args.task_id), stop, found.work.clock)
        line, passed = _claimed(found, alive)
    except Exception as error:  # a fault of the environment or a defect: counted, so it cannot relaunch forever
        line, passed = _counted(found, AttemptResult("unavailable", "fault:" + type(error).__name__)), False
    finally:
        lock.release()
    log(line)
    return 0 if passed else 1


def _claimed(found: _Registered, alive: KeepAlive) -> tuple[str, bool]:
    """Under the lock: one renewal, then the checks inside the keep-alive; a conclusion is written and the slot released."""
    alive.renew()
    ended: Ended = Verdict("failed", "claim_lost")
    if alive.word() == "lost":  # the reconcile still marks its gone unfinished results before the conclusion
        with contextlib.suppress(StoreRefused, StoreUnavailable):
            reconcile(found.work, _target(found))
    else:
        with keeping(alive):
            ended = validate(found.work, _target(found), renewal(alive))
    if isinstance(ended, AttemptResult):
        verdict = concluded(ended)
        if verdict is None:
            return f"{_counted(found, ended)} claim={alive.word()}", False
        ended = verdict
    return _ended(found, ended, alive.word())


def _ended(found: _Registered, verdict: Verdict, claim: str) -> tuple[str, bool]:
    """The conclusion, written once (fenced), then the settled release of the entry's own slot under its lock."""
    work, key = found.work, found.row.key
    try:
        work.store.conclude(key, verdict.outcome, verdict.reason, work.clock(), verdict.seen)
    except StoreRefused as refused:
        return f"refused {refused.reason} claim={claim}", False
    except StoreUnavailable:
        return f"{_counted(found, AttemptResult('unavailable', 'store'))} claim={claim}", False
    release = ChecksRelease(work.store, work.checkouts, work.slot_files, work.entry_seen, _unheld, work.clock,
        work.seen, work.scratch, ids=work.ids)
    word = release_word(release.release(key, False, found.me))
    shown = verdict.outcome if verdict.reason is None else f"{verdict.outcome}:{verdict.reason}"
    return f"collected {shown} claim={claim} release={word}", verdict.outcome == "passed"


def _target(found: _Registered) -> Target:
    """The checks attempt's validation: X in its held slot, `main` watched from its target, its own profile digest."""
    store, row = found.work.store, found.row
    return Target(row.key, row.repo_id, found.slot_path, row.commit, row.required, row.deadline, row.target,
                  lambda digest: store.profiled(row.key, digest))


def main(argv: Sequence[str] | None = None) -> int:
    os.dup2(2, 1)  # stdout joins stderr, the checks attempt's entry.log; stdin is never read
    tracker_located()  # before any thread or bd call: the stored tracker root decides the tracker bd renews the claim at

    def log(line: str) -> None:
        print(line, file=sys.stderr, flush=True)

    try:
        args = arguments(sys.argv[1:] if argv is None else argv)
        if args is None:
            log("refused usage")
            return 2
        opened = partial(open_checking, views=GitViews(args.read_seconds))
        return enter(args, opened, inspect_process, log, tracker_claims().heartbeat_for, threading.Event())
    except BaseException as error:  # the type name only, never its text
        log("failed " + type(error).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
