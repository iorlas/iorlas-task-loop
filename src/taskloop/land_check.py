"""The land's local side (tl-8bh9.14.8 sections 6 and 11): its ports (`LandPorts`), a candidate's insert with its slot's
reservation, the foreground validation of a pending candidate in its slot, and the release of a slot a candidate holds.

The insert is one write transaction: a slot's reservation (`admit.reserve` of the lowest observed-free slot still unheld,
D its HEAD) and `land_store.insert` when S validates; no slot and `same_tree` (or `no_change`) otherwise. The validation,
in the `tl step land` process, never through an entry: the slot's custody (`landing`, never waiting: `unavailable
slot_busy`, also what a second concurrent land of the task meets), held to the release; under it the land process's
identity written on the candidate (`LandStore.hold`, replacing a stored one only when it is gone); one claim renewal (lost
concludes `failed claim_lost` after the reconcile), then the keep-alive around the shared validation (`validate.validate`
at S, `main` not watched: the required names came from origin's immutable O); a terminal word concludes the candidate
(`validate.concluded`), a relaunchable one leaves it pending and answers `unavailable <word>` (nothing relaunches a land
but the person); then the settled release of the slot under the lock it holds (`check_release`'s candidate target, `me`
the land's own identity). A Ctrl-C (`KeyboardInterrupt`) unwinds through the keep-alive and the lock; the shelf's
supervision stops the running check's tree, and the rerun's reconcile marks it `interrupted`.
"""

import contextlib
import secrets
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from git_porcelain import Repo

from taskloop.admit import AdmitRefused, Tasks, free_slots, issued, reserve, unheld
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey, AttemptResult, Checkouts, EntryIdentity, Replaced
from taskloop.check_admit import heads
from taskloop.check_release import CandidateTarget, ChecksRelease
from taskloop.check_store import ChecksRow, Required
from taskloop.claim_lease import HeartbeatFor, KeepAlive, Stop, keeping, renewal
from taskloop.composition import Checking
from taskloop.factory_schema import LANDING
from taskloop.land_store import LandAdmitted, LandRow, LandStore, Settled, insert
from taskloop.operations import Failed
from taskloop.profile import ProfileFiles
from taskloop.repo import RepoId
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable
from taskloop.slot_release import NotReleased, release_word
from taskloop.slots import Probe, SlotGit
from taskloop.tracker_client import Close
from taskloop.validate import Ended, Target, Verdict, concluded, reconcile, validate

RACED = "Another land of the task, or a change of its attempts, came first: `tl step show TASK`."
type Squash = tuple[int, str, str, bool, Required]  # number, O, S, S's tree is X's, the required names at O


@dataclass(frozen=True)
class LandPorts:
    """The land's ports: the validation's (`work`: the checks store, setup runs, evidence, slot views and files, the slot
    environment, the block, the process observations, the scratch, the clock, the scrubbed environment), the candidates'
    store, the person's checkout's remote-capable view and its profile port, the tracker read and claim heartbeat, a new
    stop event per keep-alive, this process's identity, the slot lock's probe and custody, this process's environment
    (read for the push bar only), and the tracker's close (`tracker_client`: as `taskloop`, fenced on the assignee)."""

    work: Checking
    lands: LandStore
    remotes: Checkouts
    profiles: Callable[[Path], ProfileFiles]
    tasks: Tasks
    heartbeat_for: HeartbeatFor
    stop: Callable[[], Stop]
    me: Callable[[], EntryIdentity | None]
    probe: Probe
    custody: Callable[[str, str], AbstractContextManager[None]]
    environ: Mapping[str, str]
    close: Close


def _release(ports: LandPorts, hold: Callable[[str, str], AbstractContextManager[None]]) -> ChecksRelease:
    work = ports.work
    return ChecksRelease(work.store, work.checkouts, work.slot_files, work.entry_seen, hold, work.clock, work.seen, work.scratch)


def released(ports: LandPorts, row: LandRow | None) -> tuple[LandRow | None, str | None] | tuple[Failed, None]:
    """Section 4 step 5: a candidate still holding its slot after its validation (or superseded) is released first, under
    the slot's custody. Held, a pushable or delivered one still goes on (its release word carried); any other stops."""
    if row is None or not row.holds_slot or row.pending:
        return row, None
    result = _release(ports, ports.custody).release_of(CandidateTarget(ports.lands), row.key, False, ports.me())
    if isinstance(result, NotReleased) and not (row.pushable or row.delivery is not None):
        return Failed(result.kind, result.reason, result.detail), None
    return ports.lands.row(row.key) or row, release_word(result)


def _settled(ports: LandPorts, checks: ChecksRow, squash: Squash, validation: Settled) -> LandRow | Failed:
    """A candidate with no slot: validated `same_tree` (or `no_change`, delivered at insert) in one write."""
    number, o, s, same, required = squash
    key = AttemptKey(uuid4().hex, secrets.token_hex(16), 0)  # no reservation: the generation names none
    con = ports.lands.connect()
    if con is None:
        raise StoreUnavailable("Factory database unavailable")
    with ports.lands.begin(con):
        insert(con, LandAdmitted(key, checks.key.attempt_id, number, o, s, same, required, None, None, None, validation,
                                 ports.work.clock()))
    return ports.lands.row(key) or Failed("unavailable", "changed")


def _reserved(ports: LandPorts, repo: Repo, checks: ChecksRow, squash: Squash, deadline: float) -> LandRow | Failed:
    """A pending candidate and its slot's reservation, in one write transaction (the lowest observed-free slot unheld)."""
    number, o, s, same, required = squash
    con, repo_id = ports.lands.connect(), RepoId(checks.repo_id)
    if con is None:
        raise StoreUnavailable("Factory database unavailable")
    views = free_slots(con, repo, SlotGit(ports.work.checkouts, ports.work.slot_files), repo_id, ports.probe)
    free = views if not isinstance(views, tuple) else heads(repo, views)
    if isinstance(free, AdmitRefused) and (found := _held(ports, checks)) is not None:
        return found
    if not isinstance(free, tuple):
        detail = "Every slot is in use: rerun when one is free, or stop rounds." if isinstance(free, AdmitRefused) else free.detail
        return Failed("unavailable", free.reason if isinstance(free, AdmitRefused) else free.what, detail)
    key = AttemptKey(uuid4().hex, secrets.token_hex(16), issued(con, repo_id, tuple(each.name for each in free)) + 1)
    with ports.lands.begin(con):
        chosen = next((slot for each in free if (slot := unheld(con, repo_id, each, key.reservation_generation)) is not None), None)
        if chosen is None:
            return _raced(con, checks, number)
        reserve(con, repo_id, chosen[0], key)
        insert(con, LandAdmitted(key, checks.key.attempt_id, number, o, s, same, required, chosen[0], chosen[1], deadline, None,
                                 ports.work.clock()))
    return ports.lands.row(key) or Failed("unavailable", "changed")


def _raced(con: sqlite3.Connection, checks: ChecksRow, number: int) -> Failed:
    """No slot left at this candidate's generation: another land of the task came first (a candidate numbered this one or
    later, or `LANDING`), else every slot is in use."""
    found = con.execute(f"SELECT (SELECT coalesce(max(number),0) FROM land_candidate WHERE checks_attempt_id=c.attempt_id),{LANDING} "
                        "FROM checks_attempt c WHERE c.attempt_id=?", (checks.key.attempt_id,)).fetchone()
    if found is not None and (int(found[0]) >= number or found[1]):
        return Failed("refused", "landing", f"{RACED} Nothing was recorded.")
    return Failed("unavailable", "no_free_slot", "Every slot is in use: rerun when one is free, or stop rounds.")


def inserted(ports: LandPorts, repo: Repo, checks: ChecksRow, squash: Squash, settled: Settled | None, deadline: float) -> LandRow | Failed:
    """The candidate's row: settled with no slot, or pending in a reserved slot. A fence lost to another land (or a
    changed task) is its refusal word: `landing`, `not_checked`, `not_done`."""
    try:
        return _reserved(ports, repo, checks, squash, deadline) if settled is None else _settled(ports, checks, squash, settled)
    except StoreRefused as refused:
        return (_held(ports, checks) if refused.reason == "landing" else None) or Failed(
            "refused", refused.reason, f"{RACED} Nothing was recorded.")


def _held(ports: LandPorts, checks: ChecksRow) -> Failed | None:
    """The latest candidate, validated, still holds its slot (its release was held): `Next: release`, not another land."""
    held = ports.lands.latest(checks.key.attempt_id)
    if held is None or not held.holds_slot or held.pending:
        return None
    return Failed("refused", "landing", f"The land candidate {held.number} still holds its slot {held.slot} (its release was "
                  "held): rerun `tl step land`, which retries the release first, or `tl step release TASK`. Nothing was recorded.")


def _unheld(_slot_path: str, _candidate_id: str) -> AbstractContextManager[None]:
    """The land's own release runs inside the slot lock it already holds."""
    return nullcontext()


def _holder(ports: LandPorts, row: LandRow, me: EntryIdentity) -> Failed | None:
    """Under the custody: this process's identity on the candidate; a stored one is replaced only when it is gone."""
    stored, replacing = row.entry, None
    if stored is not None and stored != me:
        seen = ports.work.entry_seen(stored)
        if seen in ("matching", "unknown"):
            return Failed("unavailable", "land_running" if seen == "matching" else "observe",
                          f"The land process {stored[0]} of this candidate may still run: rerun once it ended.")
        replacing = Replaced(stored, "gone" if seen == "gone" else "different_process")
    if stored == me:
        return None
    held = ports.lands.hold(row.key, me, replacing)
    return None if held == "accepted" else Failed("unavailable", "changed", "Another land took the candidate: rerun.")


def _ended(ports: LandPorts, row: LandRow, target: Target) -> Ended:
    """One renewal, then the validation inside the keep-alive (lost: only the reconcile, then `claim_lost`)."""
    alive = KeepAlive(ports.heartbeat_for(row.tracker_root, row.task_id), ports.stop(), ports.work.clock)
    alive.renew()
    if alive.word() == "lost":
        with contextlib.suppress(StoreRefused, StoreUnavailable):
            reconcile(ports.work, target)
        return Verdict("failed", "claim_lost")
    with keeping(alive):
        return validate(ports.work, target, renewal(alive))


def _custody(ports: LandPorts, row: LandRow, slot_path: str, me: EntryIdentity) -> LandRow | Failed:
    """Under the slot's lock: the identity, the validation, the conclusion, then the settled release of the slot."""
    refused = _holder(ports, row, me)
    if refused is not None:
        return refused
    lands, key = ports.lands, row.key
    target = Target(key, row.repo_id, slot_path, row.commit, row.required, row.deadline or 0.0, None,
                    lambda digest: lands.profiled(key, digest))
    ended = _ended(ports, row, target)
    if isinstance(ended, AttemptResult):
        verdict = concluded(ended)
        if verdict is None:
            return Failed("unavailable", ended.reason, "The validation could not go on: rerun `tl step land`.")
        ended = verdict
    try:
        lands.conclude(key, ended.outcome, ended.reason, ports.work.clock())
    except StoreRefused as refused_by:
        return Failed("unavailable", refused_by.reason, "The candidate changed during its validation: rerun.")
    _release(ports, _unheld).release_of(CandidateTarget(lands), key, False, me)
    return lands.row(key) or Failed("unavailable", "changed")


def validated(ports: LandPorts, row: LandRow) -> LandRow | Failed:
    """The pending candidate's validation in its held slot, under the slot's custody; the concluded row."""
    slot_path, me = ports.lands.slot_path(row.key), ports.me()
    if slot_path is None:
        return Failed("unavailable", "changed", "The land candidate no longer holds its slot: rerun.")
    if me is None:
        return Failed("unavailable", "observe", "This process's own identity could not be read: rerun.")
    try:
        with ports.custody(slot_path, row.key.attempt_id):
            return _custody(ports, row, slot_path, me)
    except SlotBusy:
        return Failed("unavailable", "slot_busy", "Another land, entry or release holds the candidate's slot: rerun.")
    except SlotLockUnavailable:
        return Failed("unavailable", "lock", "The slot's lock file cannot be opened.")
