"""Release a checks attempt's slot reservation, and abandon a checks attempt (tl-8bh9.14.6 section 10): the same shape and
words as `slot_release`, whose park (`park_slot`), reservation removal (`free`) and setup stop rule (`setup_stopped`) it
shares; its record is `check_store.record_release`.

Two modes. settled (`tl step release`, and the checks entry itself once concluded): the attempt `concluded`, else
`refused not_terminal`. abandon: any phase; it never touches the tracker claim (the implement attempt's abandon, which
follows it, returns that). Before anything changes, in order: the stop proof (the registered entry, `me` passing; the
latest setup run's unsettled command; every unsettled result of the latest block, each through `setup_seen`, boot-aware:
alive `held:setup_running` / `held:check_running`, unknown `unavailable setup_unknown` / `check_unknown`; never
signalled), then the slot's lock (`hold`, never waiting), then the reset of a slot listed detached at X back to exactly X
(`environment.reset_to`: the untracked leftovers of a passed block would otherwise refuse the park), then the park at D
(`held:slot_dirty`, `held:slot_branch` and the other refusals of `park_slot` stand), then one write transaction fenced on
the `rev` and phase the proof read, the held reservation and no earlier release, then the scratch emptied, best effort. A
released attempt is only flipped to abandoned (the latest one of its implement attempt, once).
"""

import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from git_porcelain import GitUnavailable
from stream_proc import OwnedProcess

from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import AttemptKey, Checkouts, EntryIdentity, Observe, SlotFiles
from taskloop.check_store import ChecksRow, CheckStore, ResultRow, held_slot, record_release, unsettled
from taskloop.environment import reset_to
from taskloop.factory_schema import current
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
class _Row:
    """What the release reads before anything changes: the attempt (with X and D), its held reservation's slot path
    (None when not held), the latest setup run's unsettled command and the latest block's unsettled results."""

    checks: ChecksRow
    slot_path: str | None
    setup: OwnedProcess | None
    results: tuple[ResultRow, ...]


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


@dataclass(frozen=True)
class ChecksRelease:
    """`hold` is the slot's custody around the reset, the park and the transaction: `slot_lock.custody` for `tl step
    release`, a no-op for the checks entry, which holds the lock already."""

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
        try:
            row = self._read(key)
            if row is None:
                return NotReleased("refused", "absent", f"No such checks attempt. {NOTHING}")
            if row.checks.released_at is not None:
                return self._pending(row.checks, abandon)
        except (sqlite3.Error, StoreUnavailable) as error:
            return NotReleased("unavailable", "store", f"{type(error).__name__}. {NOTHING}")
        refused = self._refusal(row, abandon, me)
        return refused or self._held(row, abandon)

    @contextmanager
    def _connected(self) -> Generator[sqlite3.Connection]:
        con = self.store.connect()
        if con is None or not current(con):
            raise StoreUnavailable("Factory database unavailable or incompatible")
        yield con

    def _read(self, key: AttemptKey) -> _Row | None:
        checks = self.store.row(key)
        if checks is None:
            return None
        with self._connected() as con:
            return _Row(checks, held_slot(con, key), running(con, key.attempt_id), unsettled(con, key.attempt_id))

    def _refusal(self, row: _Row, abandon: bool, me: EntryIdentity | None) -> NotReleased | None:
        """Read before anything changes: the reservation held, concluded (settled only), the stop proof."""
        if row.slot_path is None:
            return NotReleased("unavailable", "changed", f"The checks attempt no longer holds its reservation. {NOTHING}")
        if not abandon and row.checks.phase != "concluded":
            return NotReleased("refused", "not_terminal", f"The checks have not concluded: relaunch them, or abandon. {NOTHING}")
        return (entry_stopped(self.observe, me, row.checks.entry) or setup_stopped(self.setup_seen, row.setup)
                or checks_stopped(self.setup_seen, row.results))

    def _pending(self, checks: ChecksRow, abandon: bool) -> ReleaseResult:
        """Released before: an abandon flips it (no Git, no lock); anything else changes nothing."""
        if not abandon or checks.abandoned:
            return AlreadyReleased(checks.slot, "kept", checks.abandoned)
        if not self.store.abandon_released(checks.key):
            return NotReleased("unavailable", "changed", f"Another release changed it first, or a later checks attempt exists. {NOTHING}")
        return Released(checks.slot, None, False, "kept", True)

    def _held(self, row: _Row, abandon: bool) -> Released | NotReleased:
        slot_path = row.slot_path or ""
        try:
            with self.hold(slot_path, row.checks.key.attempt_id):
                return self._parked(row, Path(slot_path), abandon)
        except SlotBusy:
            return NotReleased("unavailable", "slot_busy", f"Another entry or release holds the slot. {NOTHING}")
        except SlotLockUnavailable:
            return NotReleased("unavailable", "lock", f"The slot's lock file cannot be opened. {NOTHING}")

    def _parked(self, row: _Row, path: Path, abandon: bool) -> Released | NotReleased:
        """Under the lock: the reset to X, the park at D, then the transaction and the scratch."""
        checks = row.checks
        try:
            self._reset(checks, path)
            slot = park_slot(self.checkouts, self.slot_files, path, checks.repo_id, checks.slot_head, None)
        except GitUnavailable as error:
            return NotReleased("unavailable", "git", f"Git could not read, reset or park the slot ({type(error).__name__}): inspect it, "
                               "then rerun. Nothing was recorded.")
        if isinstance(slot, NotReleased):
            return slot
        head, parked = slot
        where = "No Git write" if parked is None else f"The slot was parked at {parked}"
        try:
            recorded = self._record(checks, head, abandon)
        except (sqlite3.Error, StoreUnavailable) as error:
            return NotReleased("unavailable", "store", f"{type(error).__name__}. {where}; nothing was recorded.")
        if not recorded:
            return NotReleased("unavailable", "changed", f"The checks attempt changed after the stop proof. {where}; nothing was recorded.")
        self.scratch(path)  # best effort: the next preparation empties it again
        return Released(checks.slot, parked, True, "kept", abandon)

    def _reset(self, checks: ChecksRow, path: Path) -> None:
        """A slot the view lists detached at X goes back to exactly X (tracked, untracked and ignored files); any other
        state is left for the park to judge (an attached HEAD would carry its branch)."""
        state = observe_slot(self.checkouts, self.slot_files, str(path), checks.repo_id)
        if isinstance(state, SlotState) and (state.head, state.branch) == (checks.commit, None):
            reset_to(self.checkouts(path, git_dir=state.gitdir), path, checks.commit)

    def _record(self, checks: ChecksRow, head: str, abandon: bool) -> bool:
        """One write transaction, fenced on what the proof read: the release recorded, the reservation out."""
        key = checks.key
        with self._connected() as con, self.store.begin(con):
            if not record_release(con, key, (checks.rev, checks.phase), head, self.clock(), abandon):
                return False
            free(con, checks.repo_id, checks.slot, key.attempt_id, key.reservation_generation)
        return True
