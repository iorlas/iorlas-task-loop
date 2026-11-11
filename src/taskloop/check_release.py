"""Release a slot reservation of a checks attempt or a land candidate, and abandon either (tl-8bh9.14.6 section 10,
tl-8bh9.14.8 sections 6 and 13): one release owner over a `ReleaseTarget` (`ChecksTarget`, `CandidateTarget`), the same
shape and words as `slot_release`, whose park (`park_slot`), reservation removal (`free`) and stop rules
(`entry_stopped`, `setup_stopped`) it shares; the records are `check_store.record_release` and
`land_store.record_release`.

Two modes. settled (`tl step release`, the checks entry itself once concluded, the land once its validation concluded):
the attempt `concluded` or the candidate validated, else `refused not_terminal`. abandon: any phase; it never touches the
tracker claim (the implement attempt's abandon, which follows it, returns that). Before anything changes, in order: the
target's own refusals (the reservation no longer held is `unavailable changed`; a candidate delivered refuses the abandon
`landed`, a pushable one `landing`), the stop proof (the registered entry or the land process stored on the candidate,
`me` passing; the latest setup run's unsettled command; every unsettled result of the latest block, each through
`setup_seen`, boot-aware: alive `held:setup_running` / `held:check_running`, unknown `unavailable setup_unknown` /
`check_unknown`; never signalled), then the slot's lock (`hold`, never waiting) and under it the read, the refusals
and the proof again (any other change since is `unavailable changed`), then the reset of a slot listed detached at
the commit (X, or S) back to exactly it (`environment.reset_to`: the untracked leftovers of a passed block would
otherwise refuse the park), then the park at D (`held:slot_dirty`, `held:slot_branch` and the other refusals of
`park_slot` stand), then one write transaction fenced on the `rev` and phase (or validation) the proof read, the held
reservation and no earlier release, then the scratch emptied, best effort. A released checks attempt is only flipped to
abandoned (the latest one of its implement attempt, once); a released candidate changes nothing. A checks attempt's
abandon is refused while a land candidate of its task is delivered (`refused landed`) or holds its slot or is pushable
(`refused landing`): `factory_schema.LANDING`, fenced in the record. A candidate's abandon marks it superseded
`abandoned` (unless already superseded).
"""

import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from git_porcelain import GitUnavailable
from stream_proc import OwnedProcess

from taskloop import land_store
from taskloop.attempt_reads import StoreConnection, StoreUnavailable
from taskloop.attempt_types import AttemptKey, Checkouts, EntryIdentity, Observe, SlotFiles
from taskloop.check_store import ChecksRow, CheckStore, Recorded, ResultRow, held_slot, record_release, unsettled
from taskloop.environment import reset_to
from taskloop.factory_schema import current
from taskloop.land_store import LandRow, LandStore
from taskloop.setup_store import SetupSeen, running
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable
from taskloop.slot_release import (
    NOTHING,
    AlreadyReleased,
    NotReleased,
    ParkHold,
    Released,
    ReleaseResult,
    Scratch,
    entry_stopped,
    free,
    park_slot,
    setup_stopped,
)
from taskloop.slot_state import SlotState, observe_slot


@dataclass(frozen=True)
class Holding[R]:
    """What the release reads before anything changes, of a checks attempt or a land candidate (`row`, as read): its key,
    repository, slot and D, the commit a slot listed detached is reset to (X or S), its registered entry or land process,
    its held reservation's slot path (None when not held at the key's generation), the latest setup run's unsettled
    command and the latest block's unsettled results; `what` names it in a detail, `process` its entry in the stop proof's
    (None: the attempt's entry)."""

    row: R
    key: AttemptKey
    repo_id: str
    slot: str
    slot_head: str
    commit: str
    entry: EntryIdentity | None
    slot_path: str | None
    setup: OwnedProcess | None
    results: tuple[ResultRow, ...]
    what: str
    process: str | None = None


class ReleaseTarget[R](Protocol):
    """What one release serves (`ChecksTarget`, `CandidateTarget`): its store, its read (`refused absent`), what an earlier
    release answers (None: not released yet), its own refusals before the stop proof, and its record in the release's
    transaction."""

    def store(self) -> StoreConnection: ...

    def read(self, key: AttemptKey) -> Holding[R] | NotReleased: ...

    def released(self, held: Holding[R], abandon: bool) -> ReleaseResult | None: ...

    def refusal(self, held: Holding[R], abandon: bool) -> NotReleased | None: ...

    def record_release(self, con: sqlite3.Connection, held: Holding[R], parked: str, now: float, abandon: bool) -> Recorded: ...


@contextmanager
def _connected(store: StoreConnection) -> Generator[sqlite3.Connection]:
    con = store.connect()
    if con is None or not current(con):
        raise StoreUnavailable("Factory database unavailable or incompatible")
    yield con


def checks_stopped(seen: SetupSeen, results: tuple[ResultRow, ...]) -> NotReleased | None:
    """Every unsettled result's registered command (`setup_seen`'s rule): any alive holds the slot, any unknown is
    unavailable; one never registered ran nothing."""
    found = [(row, seen(row.process)) for row in results if row.process is not None]
    alive = next((row for row, each in found if each == "alive"), None)
    if alive is not None and alive.process is not None:
        shown = f"The check {alive.name} (process group {alive.process.pgid}) still runs: wait, or see the guide. {NOTHING}"
        return NotReleased("unsettled", "check_running", shown)
    if any(each == "unknown" for _, each in found):
        return NotReleased("unavailable", "check_unknown", f"A check's process could not be observed. {NOTHING}")
    return None


LANDED = "The task's land delivered S to origin's main: rerun `tl step land` to finish the close."
LANDING = ("A land candidate of these checks holds its slot or may already be on origin's main: run `tl step land` to land "
           "it, or `tl step land --withdraw`, then abandon.")


def _refused_by_land(recorded: Recorded, where: str) -> NotReleased | None:
    """An abandon refused by `factory_schema.LANDING`, with its guide."""
    if recorded == "landed":
        return NotReleased("refused", "landed", f"{LANDED} {where}")
    if recorded == "landing":
        return NotReleased("refused", "landing", f"{LANDING} {where}")
    return None


@dataclass(frozen=True)
class ChecksTarget:
    """A checks attempt: settled only once concluded; an earlier release is only flipped to abandoned (the latest one of
    its implement attempt, once, `NOT LANDING`); its record is `check_store.record_release`."""

    checks: CheckStore

    def store(self) -> StoreConnection:
        return self.checks

    def read(self, key: AttemptKey) -> Holding[ChecksRow] | NotReleased:
        checks = self.checks.row(key)
        if checks is None:
            return NotReleased("refused", "absent", f"No such checks attempt. {NOTHING}")
        with _connected(self.checks) as con:
            return Holding(checks, key, checks.repo_id, checks.slot, checks.slot_head, checks.commit, checks.entry, held_slot(con, key),
                           running(con, key.attempt_id), unsettled(con, key.attempt_id), "checks attempt")

    def released(self, held: Holding[ChecksRow], abandon: bool) -> ReleaseResult | None:
        """Released before: an abandon flips it (no Git, no lock); anything else changes nothing."""
        checks = held.row
        if checks.released_at is None:
            return None
        if not abandon or checks.abandoned:
            return AlreadyReleased(checks.slot, "kept", checks.abandoned)
        recorded = self.checks.abandon_released(checks.key)
        if recorded != "abandoned":
            return _refused_by_land(recorded, NOTHING) or NotReleased(
                "unavailable", "changed", f"Another release changed it first, or a later checks attempt exists. {NOTHING}")
        return Released(checks.slot, None, False, "kept", True)

    def refusal(self, held: Holding[ChecksRow], abandon: bool) -> NotReleased | None:
        if held.slot_path is None:
            return NotReleased("unavailable", "changed", f"The checks attempt no longer holds its reservation. {NOTHING}")
        if not abandon and held.row.phase != "concluded":
            return NotReleased("refused", "not_terminal", f"The checks have not concluded: relaunch them, or abandon. {NOTHING}")
        return None

    def record_release(self, con: sqlite3.Connection, held: Holding[ChecksRow], parked: str, now: float, abandon: bool) -> Recorded:
        return record_release(con, held.key, (held.row.rev, held.row.phase), parked, now, abandon)


@dataclass(frozen=True)
class CandidateTarget:
    """A land candidate holding its slot (tl-8bh9.14.8 sections 6 and 13), its stop proof with the land process's stored
    identity: settled only once validated; an abandon releases one that is pending or failed (or superseded) and marks it
    superseded `abandoned`, and refuses one delivered (`landed`) or pushable (`landing`) before anything changes; an earlier
    release changes nothing; its record is `land_store.record_release`."""

    lands: LandStore

    def store(self) -> StoreConnection:
        return self.lands

    def read(self, key: AttemptKey) -> Holding[LandRow] | NotReleased:
        found = self.lands.row(key)
        if found is None or found.slot is None or found.slot_head is None:  # validated with no slot: nothing to release
            return NotReleased("refused", "absent", f"No such land candidate holding a slot. {NOTHING}")
        with _connected(self.lands) as con:
            slot_path = land_store.held_slot(con, key)
            return Holding(found, key, found.repo_id, found.slot, found.slot_head, found.commit, found.entry, slot_path,
                           running(con, key.attempt_id), unsettled(con, key.attempt_id), "land candidate", "land process")

    def released(self, held: Holding[LandRow], abandon: bool) -> ReleaseResult | None:
        """Released before: settled changes nothing; an abandon still refuses a delivered or pushable candidate."""
        found = held.row
        if found.released_at is None:
            return None
        return _landing_of(found, abandon) or AlreadyReleased(held.slot, "kept", found.superseded == "abandoned")

    def refusal(self, held: Holding[LandRow], abandon: bool) -> NotReleased | None:
        found = held.row
        if held.slot_path is None:
            return NotReleased("unavailable", "changed", f"The land candidate no longer holds its reservation. {NOTHING}")
        if not abandon and found.validation is None:
            unfinished = "The land's validation has not concluded: rerun `tl step land`, or abandon."
            return NotReleased("refused", "not_terminal", f"{unfinished} {NOTHING}")
        return _landing_of(found, abandon)

    def record_release(self, con: sqlite3.Connection, held: Holding[LandRow], parked: str, now: float, abandon: bool) -> Recorded:
        return land_store.record_release(con, held.key, (held.row.rev, held.row.validation), parked, now, abandon)


def _landing_of(found: LandRow, abandon: bool) -> NotReleased | None:
    """An abandon of a delivered (`landed`) or pushable (`landing`) candidate: S is, or may be, on origin's `main`."""
    if not abandon:
        return None
    return _refused_by_land("landed" if found.delivery is not None else "landing" if found.pushable else "changed", NOTHING)


@dataclass(frozen=True)
class ChecksRelease:
    """`hold` is the slot's custody around the reset, the park and the transaction: `slot_lock.custody` for `tl step
    release`, a no-op for the checks entry (and the land), which holds the lock already. `release` serves the checks
    attempt of `store`; `release_of` any `ReleaseTarget` (a land candidate through `CandidateTarget`)."""

    store: CheckStore
    checkouts: Checkouts
    slot_files: SlotFiles
    observe: Observe
    hold: ParkHold
    clock: Callable[[], float]
    setup_seen: SetupSeen
    scratch: Scratch

    def release(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        """Release the checks attempt's reservation (settled) or abandon it; `me` is the calling entry's own identity."""
        return self.release_of(ChecksTarget(self.store), key, abandon, me)

    def release_candidate(self, key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        """Release a land candidate's reservation (settled) or abandon it, on the same store (`tl step release`)."""
        return self.release_of(CandidateTarget(LandStore(self.store.connect, self.store.begin)), key, abandon, me)

    def release_of[R](self, target: ReleaseTarget[R], key: AttemptKey, abandon: bool, me: EntryIdentity | None = None) -> ReleaseResult:
        """Release `target`'s reservation (settled) or abandon it; `me` is the calling entry's (or land process's) identity."""
        try:
            held = target.read(key)
            if isinstance(held, NotReleased):
                return held
            before = target.released(held, abandon)
            if before is not None:
                return before
        except (sqlite3.Error, StoreUnavailable) as error:
            return NotReleased("unavailable", "store", f"{type(error).__name__}. {NOTHING}")
        refused = target.refusal(held, abandon) or self._stopped(held, me)
        return refused or self._held(target, held, abandon, me)

    def _stopped[R](self, held: Holding[R], me: EntryIdentity | None) -> NotReleased | None:
        """The stop proof, read before anything changes: the registered entry or land process (`me` passing), the
        latest setup run's unsettled command, every unsettled result of the latest block."""
        return (entry_stopped(self.observe, me, held.entry, held.process) or setup_stopped(self.setup_seen, held.setup)
                or checks_stopped(self.setup_seen, held.results))

    def _again[R](self, target: ReleaseTarget[R], held: Holding[R], abandon: bool, me: EntryIdentity | None) -> NotReleased | None:
        """Under the lock, before any Git write: read again and prove again (a land process may have taken the custody,
        started a check and died between the first proof and the lock); any other change since is `changed`."""
        try:
            fresh = target.read(held.key)
        except (sqlite3.Error, StoreUnavailable) as error:
            return NotReleased("unavailable", "store", f"{type(error).__name__}. {NOTHING}")
        if isinstance(fresh, NotReleased):
            return fresh
        refused = target.refusal(fresh, abandon) or self._stopped(fresh, me)
        if refused is None and fresh != held:
            return NotReleased("unavailable", "changed", f"The {held.what} changed before the slot's lock was taken. {NOTHING}")
        return refused

    def _held[R](self, target: ReleaseTarget[R], held: Holding[R], abandon: bool, me: EntryIdentity | None) -> Released | NotReleased:
        slot_path = held.slot_path or ""
        try:
            with self.hold(slot_path, held.key.attempt_id):
                return self._again(target, held, abandon, me) or self._parked(target, held, Path(slot_path), abandon)
        except SlotBusy:
            return NotReleased("unavailable", "slot_busy", f"Another entry or release holds the slot. {NOTHING}")
        except SlotLockUnavailable:
            return NotReleased("unavailable", "lock", f"The slot's lock file cannot be opened. {NOTHING}")

    def _parked[R](self, target: ReleaseTarget[R], held: Holding[R], path: Path, abandon: bool) -> Released | NotReleased:
        """Under the lock: the reset to the commit, the park at D, then the transaction and the scratch."""
        try:
            self._reset(held, path)
            slot = park_slot(self.checkouts, self.slot_files, path, held.repo_id, held.slot_head, None)
        except GitUnavailable as error:
            return NotReleased("unavailable", "git", f"Git could not read, reset or park the slot ({type(error).__name__}): inspect it, "
                               "then rerun. Nothing was recorded.")
        if isinstance(slot, NotReleased):
            return slot
        head, parked = slot
        where = "No Git write" if parked is None else f"The slot was parked at {parked}"
        try:
            recorded = self._record(target, held, head, abandon)
        except (sqlite3.Error, StoreUnavailable) as error:
            return NotReleased("unavailable", "store", f"{type(error).__name__}. {where}; nothing was recorded.")
        if recorded not in ("released", "abandoned"):
            changed = NotReleased("unavailable", "changed",
                                  f"The {held.what} changed after the stop proof. {where}; nothing was recorded.")
            return _refused_by_land(recorded, f"{where}; nothing was recorded.") or changed
        self.scratch(path)  # best effort: the next preparation empties it again
        return Released(held.slot, parked, True, "kept", abandon)

    def _reset[R](self, held: Holding[R], path: Path) -> None:
        """A slot the view lists detached at the commit goes back to exactly it (tracked, untracked and ignored files); any
        other state is left for the park to judge (an attached HEAD would carry its branch)."""
        state = observe_slot(self.checkouts, self.slot_files, str(path), held.repo_id)
        if isinstance(state, SlotState) and (state.head, state.branch) == (held.commit, None):
            reset_to(self.checkouts(path, git_dir=state.gitdir), path, held.commit)

    def _record[R](self, target: ReleaseTarget[R], held: Holding[R], head: str, abandon: bool) -> Recorded:
        """One write transaction, fenced on what the proof read: the release recorded, the reservation out."""
        store, key = target.store(), held.key
        with _connected(store) as con, store.begin(con):
            recorded = target.record_release(con, held, head, self.clock(), abandon)
            if recorded in ("released", "abandoned"):
                free(con, held.repo_id, held.slot, key.attempt_id, key.reservation_generation)
        return recorded
