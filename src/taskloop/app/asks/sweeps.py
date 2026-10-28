"""The sweeps over open asks: close those whose bead is closed or gone, park those nobody answered in three days, and find answers no
run has used. Each is throttled by the mtime of a marker file, so the loop and `tl` can both call it freely."""
import contextlib
from collections.abc import Callable
from pathlib import Path

from taskloop.contracts.ask import Ask
from taskloop.contracts.enums import AskStatus
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, Beads
from taskloop.contracts.stores import HAD_PICK, ORPHAN, AskStore

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


def orphan_lines(asks: AskStore) -> list[str]:
    """One line per bead whose ask file cannot be read any more: such a bead would otherwise be parked and invisible."""
    return [f"{bead:<22} {ORPHAN}" for bead in asks.orphans()]


def reopen(asks: AskStore, store: Beads, bead: str, pick: str = "", info: str = "") -> bool:
    """Make a bead parked on a dropped ask re-askable: open again (back in the pick queue only if the park took its pick label), so the
    next run goes on from its checkpoint and raises a fresh ask. The dead file stays until that ask replaces it. -> whether reopened."""
    try:
        shown = store.show(bead)
        if shown is None:
            return False  # another repo's bead, or gone: this tracker cannot say
        if shown.status == "closed":
            asks.drop(bead)
            return False
        if shown.status != "blocked":
            return False
        store.update(bead, BeadPatch(status="open"))
        if pick and shown.metadata.get(HAD_PICK) == pick:  # the loop never adds the pick label: it only gives back one the park took
            store.add_label(bead, pick)
            store.update(bead, BeadPatch(unset_metadata=[HAD_PICK]))
        if info and info in shown.labels:
            store.remove_label(bead, info)
    except BdFailure:
        return False
    return True


def reask_orphans(asks: AskStore, store: Beads, marker: Path, now: float, pick: str = "", info: str = "",
                  say: Callable[[str], None] = print, every: float = EVERY_S) -> list[str]:
    """The sweep over dropped asks: every blocked bead of this tracker that was parked on one is reopened. -> the beads reopened."""
    if not due(marker, every, now):
        return []
    done = [b for b in asks.orphans() if reopen(asks, store, b, pick, info)]
    for b in done:
        say(f"{b}: parked on an ask that was dropped at upgrade; reopened to ask again")
    touch(marker)
    return done


def unused_answers(asks: AskStore, now: float, after_s: float = UNUSED_ANSWER_S) -> list[Ask]:
    """Answers filed and not used by any run for `after_s`: the loop is not picking the bead up (the engine's fault, not the owner's)."""
    return [a for a in asks.all() if a.status == AskStatus.ANSWERED and a.consumed is None and a.answered is not None
            and now - a.answered > after_s]


def shout(asks: AskStore, marker: Path, now: float, say: Callable[[str], None], every: float = EVERY_S) -> None:
    """Say a RED line for each answer no run used for half an hour (throttled by the marker)."""
    if due(marker, every, now):
        touch(marker)
        for k in unused_answers(asks, now):
            say("RED: " + fault_line(k, now))


def fault_line(ask: Ask, now: float) -> str:
    mins = (now - (ask.answered or now)) // 60
    return f"FAULT: ask {ask.id} of {ask.bead} was answered {mins:.0f} min ago and no run has used the answer"
