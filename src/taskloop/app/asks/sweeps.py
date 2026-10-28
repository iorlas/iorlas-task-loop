"""The sweeps over open asks: close those whose bead is closed or gone, park those nobody answered in three days, and find answers no
run has used. Each is throttled by the mtime of a marker file, so the loop and `tl` can both call it freely."""
import contextlib
from collections.abc import Callable
from pathlib import Path

from taskloop.contracts.ask import Ask
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads
from taskloop.contracts.stores import AskStore

UNUSED_ANSWER_S = 30 * 60
EVERY_S = 600
StoreAt = Callable[[str], Beads]


def due(marker: Path, every: float, now: float) -> bool:
    try:
        return now - marker.stat().st_mtime >= every
    except OSError:
        return True


def touch(marker: Path) -> None:
    with contextlib.suppress(OSError):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("")


def by_repo(live: list[Ask]) -> dict[str, list[Ask]]:
    out: dict[str, list[Ask]] = {}
    for a in live:
        if a.repo and (Path(a.repo) / ".beads").is_dir():  # which tracker to ask is unknown otherwise: bd would walk up to another
            out.setdefault(a.repo, []).append(a)
    return out


def closed_reason(store: Beads, status: dict[str, str], ask: Ask) -> str:
    if ask.bead not in status:  # the list hides gates, ephemeral and infra beads: ask about this one before saying so
        return "the bead does not exist" if store.show(ask.bead) is None else ""
    return "the bead is closed" if status[ask.bead] == "closed" else ""


def close_stale(asks: AskStore, store_at: StoreAt, marker: Path, now: float, every: float = EVERY_S) -> list[str]:
    """An open ask whose bead is closed or does not exist is closed with the reason. A bd that fails for another reason changes
    nothing, and is tried again at once. -> the bead ids closed."""
    if not due(marker, every, now):
        return []
    done: list[str] = []
    listed_any = False
    groups = by_repo(asks.pending())
    for repo, items in groups.items():
        try:
            store = store_at(repo)
            status = {b.id: b.status for b in store.find(BeadQuery(include_closed=True))}
            if not status:
                continue  # an empty answer proves nothing
            listed_any = True
            for a in items:
                why = closed_reason(store, status, a)
                if why and asks.close(a.bead, a.id, why):
                    done.append(a.bead)
        except BdFailure:
            continue
    if listed_any or not groups:  # a bd outage is no sweep
        touch(marker)
    return done


def park_stale(asks: AskStore, store_at: StoreAt, marker: Path, now: float, every: float = EVERY_S) -> list[str]:
    """An open ask nobody answered by its parks_at is parked, with a comment on the bead. It still waits: an answer un-parks it."""
    if not due(marker, every, now):
        return []
    done: list[str] = []
    for a in asks.live():
        if a.status != AskStatus.OPEN or a.answer is not None or not a.parks_at or now <= a.parks_at or not Path(a.repo or "-").is_dir():
            continue
        if asks.park(a.bead, a.id):
            done.append(a.bead)
            with contextlib.suppress(BdFailure):
                store_at(a.repo).add_comment(a.bead, f"Parked (engine): ask {a.id} got no answer in 3 days. It stays open for an answer: "
                                                      f"`tl ask answer {a.bead}`, or the dashboard.")
    touch(marker)
    return done


def unused_answers(asks: AskStore, now: float, after_s: float = UNUSED_ANSWER_S) -> list[Ask]:
    """Answers filed and not used by any run for `after_s`: the loop is not picking the bead up (the engine's fault, not the owner's)."""
    return [a for a in asks.all() if a.status == AskStatus.ANSWERED and a.consumed is None and a.answered is not None
            and now - a.answered > after_s]


def fault_line(ask: Ask, now: float) -> str:
    mins = (now - (ask.answered or now)) // 60
    return f"FAULT: ask {ask.id} of {ask.bead} was answered {mins:.0f} min ago and no run has used the answer"
