"""The registered entry process of one admitted checks attempt: `python -I -m taskloop.check_entry DB ARTIFACTS BACKLOG
TASK` (tl-8bh9.14.6 section 6), launched by `launch.Launcher` over `CheckStore`. Its stdout and stderr are the checks
attempt's `entry.log`.

It runs only as the identity the launcher registered (`refused identity` otherwise), never creates factory.db, and
signals nothing. Order: its slot's custody lock (never waiting), held to the end; the claim renewed once (lost concludes
`claim_lost`, after the reconcile below marks gone unfinished results), then kept alive by a thread until the block ends
(a later loss is only the log's `claim=`); the reconcile before any slot read or write (the latest setup run's unsettled
command and every unsettled result of the latest block, boot-aware: alive `unavailable checks:running`, unknown
`checks:unknown`; gone, an unfinished result becomes `interrupted`); the deadline (`expired`); the profile at X on the
slot's pinned view (`profile:<reason>`); `main` read (`main_moved`); a completed latest block is concluded as it stands,
never run again; X taken detached (`prepare.detach_at`); the slot reset to exactly X and set up at X
(`environment.prepare_for`, no probe); the block (`checks.Block`); `main` read again; the conclusion from the latest
block; then the settled release of its own slot under the lock it holds (`check_release`). Section 6.1: a condition the
candidate caused, or one a relaunch cannot clear, concludes `failed` with its reason and releases; an unavailable word,
or a refusal in `RELAUNCHED`, leaves the attempt `admitted` and is counted (`CheckStore.refused`, whatever the word; two
in a row stop the rounds' relaunches), and so is any other fault once the attempt is the entry's own (`unavailable
fault:<type>`). One log line of fixed words: `collected passed|failed:<reason>` then `claim=` and `release=`, or the
refusal (then `claim=` once the claim was read). Exit 0 only for `passed`.
"""

import contextlib
import hashlib
import os
import sqlite3
import sys
import threading
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from git_porcelain import GitUnavailable, Repo
from stream_proc import ProcessObservation, inspect_process

from taskloop import slot_lock
from taskloop.attempt_entry import EntryArgs, arguments, database_exists, renewal
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptResult, EntryIdentity
from taskloop.check_release import ChecksRelease
from taskloop.check_store import ChecksRow, Outcome
from taskloop.checks import BlockTarget, CheckSink, check_env, completed, conclusion, main_seen
from taskloop.claim_lease import HeartbeatFor, KeepAlive, Stop, keeping
from taskloop.composition import Checking, open_checking
from taskloop.environment import Renew, SetupFor
from taskloop.prepare import Prepared, detach_at, slot_listed
from taskloop.profile import PROFILE_PATH, Profile, Refused, read_profile
from taskloop.slot_release import release_word
from taskloop.tracker_client import tracker_claims, tracker_located

# Refusal words a relaunch may clear (counted, like every unavailable word): the slot's lock held or unopenable, a slot
# detached elsewhere with changes, and a store fence that moved under the entry.
RELAUNCHED: Final = frozenset({"slot_busy", "lock", "slot_dirty", "stale_reservation", "check_changed", "setup_changed"})


@dataclass(frozen=True)
class Verdict:
    """The checks attempt's conclusion: `failed` has a reason; `seen` is `main` when found moved."""

    outcome: Outcome
    reason: str | None = None
    seen: str | None = None


type Ended = Verdict | AttemptResult


@dataclass(frozen=True)
class _Registered:
    work: Checking
    row: ChecksRow
    me: EntryIdentity
    slot_path: str  # the held reservation's slot: its custody lock is beside it


def concluded(result: AttemptResult) -> Verdict | None:
    """Section 6.1's table: a refusal concludes `failed` with its word (`slot_unborn` as `slot:unborn`), except those in
    `RELAUNCHED`; an unavailable word never concludes (None: relaunch and count)."""
    if result.status != "refused" or result.reason in RELAUNCHED:
        return None
    return Verdict("failed", "slot:unborn" if result.reason == "slot_unborn" else result.reason)


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
    me = None if seen.kind != "matching" or seen.identity is None else (seen.identity.pid, seen.identity.start, seen.identity.boot)
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
            _reconciled(found)
    else:
        with keeping(alive):
            ended = _checked(found, renewal(alive))
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
    release = ChecksRelease(work.store, work.checkouts, work.slot_files, work.entry_seen, _unheld, work.clock, work.seen, work.scratch)
    word = release_word(release.release(key, False, found.me))
    shown = verdict.outcome if verdict.reason is None else f"{verdict.outcome}:{verdict.reason}"
    return f"collected {shown} claim={claim} release={word}", verdict.outcome == "passed"


def _checked(found: _Registered, renew: Renew) -> Ended:
    """Steps 4-12 inside the keep-alive: a conclusion, or the refusal to relaunch or conclude."""
    try:
        return _reconciled(found) or _expired(found) or _at_x(found, renew)
    except GitUnavailable:
        return AttemptResult("unavailable", "git")
    except StoreUnavailable:
        return AttemptResult("unavailable", "store")
    except StoreRefused as refused:
        return AttemptResult("refused", refused.reason)


def _reconciled(found: _Registered) -> AttemptResult | None:
    """Before any slot read or write: every command that may still hold the slot, never signalled. Gone (or never
    registered), an unfinished result is concluded `interrupted`, so its block repeats whole."""
    work, key = found.work, found.row.key
    setup = work.setups.latest(key)
    rows = [row for row in work.store.results(key) if row.unsettled]
    processes = [process for process in (None if setup is None else setup.unsettled, *(row.process for row in rows)) if process]
    seen = {work.seen(process) for process in processes}
    if "alive" in seen or "unknown" in seen:
        return AttemptResult("unavailable", "checks:running" if "alive" in seen else "checks:unknown")
    for row in rows:
        if row.conclusion is None:
            work.store.finish(key, row.block, row.position, "interrupted", None, work.clock())
    return None


def _expired(found: _Registered) -> Verdict | None:
    """Past the deadline nothing of the attempt runs (the reconcile proved it): it concludes and releases."""
    return Verdict("failed", "expired") if found.work.clock() >= found.row.deadline else None


def _moved(view: Repo, target: str) -> Verdict | None:
    """`main` read now, against the target the required names were read from (O1)."""
    seen = main_seen(view)
    return None if seen == target else Verdict("failed", "main_moved", seen)


def _profiled(found: _Registered) -> tuple[Profile, str, Path] | AttemptResult:
    """Step 6: the profile at X and its digest, read on the slot's pinned view (its verified Git directory, returned)."""
    work, row = found.work, found.row
    state = slot_listed(work.checkouts, work.slot_files, found.slot_path, row.repo_id)
    if isinstance(state, AttemptResult):
        return state
    files = work.profiles(Path(found.slot_path), state.gitdir)
    profile, blob = read_profile(files, row.commit), files.blob(row.commit, PROFILE_PATH)
    if isinstance(profile, Refused):
        return AttemptResult("refused", f"profile:{profile.reason}")
    if not isinstance(profile, Profile) or not isinstance(blob, bytes):
        return AttemptResult("unavailable", "git")
    return profile, hashlib.sha256(blob).hexdigest(), state.gitdir


def _at_x(found: _Registered, renew: Renew) -> Ended:
    """Steps 6-9: the profile at X, `main` (also before a completed latest block is concluded as it stands: a candidate
    that moved it and then killed its entry never passes), then X taken detached."""
    work, row = found.work, found.row
    read = _profiled(found)
    if isinstance(read, AttemptResult):
        return read
    profile, digest, gitdir = read
    results = work.store.results(row.key)
    moved = _moved(work.checkouts(Path(found.slot_path), git_dir=gitdir), row.target)
    if moved is None and completed(results, profile.checks, row.required):
        return Verdict(*conclusion(results, row.required))
    prepared = moved or detach_at(work.checkouts, work.slot_files, found.slot_path, row.repo_id, row.commit)
    if not isinstance(prepared, Prepared):
        return prepared
    return _environment(found, prepared, renew) or _block(found, profile, prepared, digest)


def _environment(found: _Registered, prepared: Prepared, renew: Renew) -> Ended | None:
    """Step 10: the slot reset to exactly X and set up at X, no probe; two failed setup runs conclude `setup:<conclusion>`
    of the latest."""
    work, row = found.work, found.row
    target = SetupFor(row.key, Path(found.slot_path), row.commit, None, row.deadline, True)
    stopped = work.preparation.prepare_for(target, prepared, renew, work.environ(), probe=None)
    if stopped is None or stopped != AttemptResult("refused", "environment:failed"):
        return stopped
    latest = work.setups.latest(row.key)
    return Verdict("failed", f"setup:{'failed' if latest is None or latest.conclusion is None else latest.conclusion}")


def _block(found: _Registered, profile: Profile, prepared: Prepared, digest: str) -> Ended:
    """Steps 11-12: the block, `main` again, then the conclusion from the latest block."""
    work, row, path = found.work, found.row, Path(found.slot_path)
    number = work.store.block(row.key)
    work.store.profiled(row.key, digest)
    view = work.checkouts(path, git_dir=prepared.gitdir)
    target = BlockTarget(path, view, row.commit, row.required, row.deadline, check_env(work.environ(), path))
    stopped = work.block.run(target, CheckSink(work.store, row.key, work.files, work.clock), number, profile.checks)
    if stopped is not None:
        return stopped
    return _moved(view, row.target) or Verdict(*conclusion(work.store.results(row.key), row.required))


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
        return enter(args, open_checking, inspect_process, log, tracker_claims().heartbeat_for, threading.Event())
    except BaseException as error:  # the type name only, never its text
        log("failed " + type(error).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
