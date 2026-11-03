"""The one slot table: configured slots, the slot beads of this machine, the live runs and the dirs, folded into `SlotView`s.

The dash, `tl status` and doctor all call `build_slot_table`; none counts slots or reads a slot's state on its own. It lives in
contracts because the dashboard may import nothing else of the engine."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from functools import partial

from taskloop.contracts.bead import Bead
from taskloop.contracts.slots import SlotTable, SlotView

WORKTREE = "worktree"


@dataclass(frozen=True)
class LiveSlot:
    """A run that is alive in a slot: its name (the holder), its bead, when it began and its pid when known."""

    run: str
    bead: str = ""
    since: str = ""
    pid: int | None = None


def slot_name(b: Bead) -> str:
    return b.title.split()[-1]


def _hold_until(b: Bead) -> float:
    try:
        return float(b.metadata.get("hold_until") or 0)
    except TypeError, ValueError:
        return 0.0


def _index(name: str) -> int:
    """`s4` -> 4; a name that is not s<N> belongs to no configured count."""
    return int(name[1:]) if name[:1] == "s" and name[1:].isdigit() else 0


def build_slot_table(
    beads: Sequence[Bead],
    count: int,
    live: Mapping[str, LiveSlot],
    dirs: Collection[str] | None,
    now: float,
    source: str,
    source_sha: str = "",
    targets: Collection[str] = (),
) -> SlotTable:
    """Slots s1..s<count> (even with no slot bead yet) plus any slot bead above the count that still holds work.

    beads: this machine's slot beads (`slots_of(rows, host)`). live: slot name -> the run alive in it. dirs: names of the
    slot folders that exist (None: not looked at, assumed to). targets: ids of beads that may be started (a claim naming one is
    `setup`, one naming none is `claimed`)."""
    by_name = {slot_name(b): b for b in beads}
    names = sorted({f"s{i}" for i in range(1, count + 1)} | set(by_name), key=lambda n: (_index(n) or 10**9, n))
    views = [slot_view(n, by_name.get(n), live.get(n), dirs is None or n in dirs, _index(n) > count, now, set(targets)) for n in names]
    return SlotTable(configured=count, slots=views, source=source, source_sha=source_sha)


def slot_view(name: str, b: Bead | None, run: LiveSlot | None, dir_exists: bool, beyond: bool, now: float, targets: set[str]) -> SlotView:
    m = b.metadata if b else {}
    view = partial(SlotView, id=name, dir_exists=dir_exists, beyond_count=beyond)
    if b is not None and _hold_until(b) > now:
        by = str(m.get("held_by") or "?")
        reason = next(iter(str(m.get("held_why") or "").strip().splitlines()), "") or "held"
        return view(
            state="held",
            holder=by,
            since=str(m.get("held_since") or ""),
            held_reason=reason,
            held_until=_hold_until(b),
            idle_why=f"held by {by}: {reason}",
        )
    if run is not None:
        return view(state="running", holder=run.run, bead=run.bead, since=run.since, pid=run.pid)
    if b is not None and b.status != "open":
        target = str(m.get("held_bead") or "")
        since = str(m.get("held_since") or b.updated_at)
        if target in targets:
            return view(state="setup", holder=b.assignee, bead=target, since=since, idle_why=f"starting {target}")
        state = "claimed" if dir_exists else "dead"
        return view(
            state=state,
            holder=b.assignee,
            since=since,
            idle_why=f"claimed by {b.assignee or '?'}, " + ("no live run" if dir_exists else "its folder is gone"),
        )
    if beyond:
        return view(state="retiring", idle_why="above slots.count")
    return view(state="free")


@dataclass(frozen=True)
class SlotSource:
    """Where a repo's slot count comes from and what the machine has: read once per profile change by the launcher's port."""

    host: str = ""
    count: int = 0
    source: str = ""  # the base ref (origin/main) the profile was read from, or "worktree"
    sha: str = ""
    dirs: frozenset[str] | None = None  # names of the existing slot folders; None: unknown
