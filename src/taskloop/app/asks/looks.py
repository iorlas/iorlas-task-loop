"""The owner's answer to a look item (`Intake.look`): good settles the item, redo files a follow-up bead that carries the note and the
pictures, undo takes either back. The items live in the look bead's look_doc row (tlkernel/lookrows.py), written by compare-and-set, never
in the bead's metadata; the look bead closes when no item waits. Items
are keyed by their id ("<source bead>#<n>", contracts/gallery.py). Every failure is a reason the owner can read; nothing is half done."""
import contextlib
import threading
from typing import Any

from tlkernel import factorydb, gallery
from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, BeadPatch, BeadQuery, Beads, NewBead
from tlkernel.ids import BeadId, is_bead_id
from tlkernel.lookrows import LookRaced, LookRows

NOTE_MAX = 2000
VERDICTS = ("good", "redo", "undo")
_one_at_a_time = threading.Lock()  # two clicks never file two follow-ups


def row(b: Bead) -> gallery.Item:
    return {"metadata": b.metadata, "description": b.description, "labels": b.labels, "status": b.status, "title": b.title}


def failure(err: BdFailure) -> str:
    return (err.error.text.strip().splitlines() or ["no output"])[-1][:200]


def held_items(rows: LookRows, b: Bead) -> list[gallery.Item]:
    """The items of a look bead: its row, else what the bead carried before the row (metadata `looks`, or its description)."""
    have = rows.items(b.id)
    return have if have is not None else gallery.stored(b.id, row(b))


def find(store: Beads, rows: LookRows, item: str, look_bead: str) -> tuple[Bead | None, str, str]:
    """(the look bead holding `item`, the item's id, "") else (None, "", why). `look_bead` names the bead when the caller knows it;
    otherwise every owner-look bead is searched, and the item may also be named by its source bead when that source has exactly one
    item that still waits."""
    if look_bead:
        found = store.show(look_bead) if is_bead_id(look_bead) else None
        if found is None or gallery.LABEL not in found.labels:
            return None, "", f"The look bead {look_bead} no longer exists."
        return found, item, ""
    hits: list[tuple[Bead, gallery.Item]] = []
    for b in store.find(BeadQuery(label=gallery.LABEL, include_closed=True)):
        shown = store.show(b.id) or b
        hits += [(shown, e) for e in held_items(rows, shown)]
    exact = [(b, e) for b, e in hits if e.get("id") == item]
    sourced = [(b, e) for b, e in hits if e.get("bead") == item and e.get("status") not in ("good", "redo")]
    pick = exact or (sourced if len(sourced) == 1 else [])
    return (pick[0][0], str(pick[0][1]["id"]), "") if pick else (None, "", "That item is gone. Reload the page.")


def answer(store: Beads, rows: LookRows, item: str, verdict: str, note: str, now: float, look_bead: str = "") -> tuple[str, str]:
    """-> (the item's status after the answer: open, good or redo, "" or why nothing changed)."""
    note = note.strip()[:NOTE_MAX]
    if verdict not in VERDICTS:
        return "", "The request was not understood."
    if verdict == "redo" and not note:
        return "", "Write what to change first."
    with _one_at_a_time:
        try:
            return _apply(store, rows, item, verdict, note, now, look_bead)
        except BdFailure as err:
            return "", f"bd did not answer ({failure(err)}). Nothing was changed."


def _apply(store: Beads, rows: LookRows, item: str, verdict: str, note: str, now: float, look_bead: str) -> tuple[str, str]:
    bead, item, why = find(store, rows, item, look_bead)
    if bead is None:
        return "", why
    e = next((x for x in held_items(rows, bead) if x.get("id") == item), None)
    if e is None:
        return "", "That item is gone. Reload the page."
    state = e.get("status") if e.get("status") in ("good", "redo") else "open"
    if verdict == "undo" and state == "open":
        return "open", ""
    if verdict != "undo" and state != "open":
        return "", f"Already answered ({state}). Take that back first."
    made = ""
    if verdict == "redo":
        try:
            made = file_redo(store, bead.id, e, note)
        except BdFailure as err:
            return "", f"bd refused the follow-up bead: {failure(err)}"
    return _record(store, rows, bead, (item, verdict, note, now), made)


def _answered(items: list[gallery.Item], said: tuple[str, str, str, float], made: str) -> list[gallery.Item] | None:
    """`items` with the answer in the item, None when the item is not there. The row is read fresh on every try: the engine may have
    filed items meanwhile, and they stay."""
    item, verdict, note, now = said
    kept = [dict(x) for x in items]
    e = next((x for x in kept if x.get("id") == item), None)
    if e is None:
        return None
    if verdict == "undo":
        e.update(status="open", redo_bead="", answer_note="", answered=0)
    elif verdict == "good":
        e.update(status="good", answer_note=note, answered=now)
    else:
        e.update(status="redo", redo_bead=made, answer_note=note, answered=now)
    return kept


def _record(store: Beads, rows: LookRows, shown: Bead, said: tuple[str, str, str, float], made: str) -> tuple[str, str]:
    """Write the answer into the item's row (compare-and-set), then close or reopen the look bead. The bead's metadata is not written."""
    item, verdict = said[0], said[1]
    shown = store.show(shown.id) or shown
    before: dict[str, object] = {}

    def change(items: list[gallery.Item]) -> list[gallery.Item] | None:
        before.update(next((x for x in items if x.get("id") == item), {}))
        return _answered(items, said, made)

    try:
        items = rows.modify(shown.id, lambda: gallery.stored(shown.id, row(shown)), change)
    except (LookRaced, factorydb.DatabaseError) as err:
        drop(store, made)
        return "", f"The answer was not saved ({err}). Nothing was changed."
    if items is None:
        drop(store, made)
        return "", "That item is gone. Reload the page."
    if verdict == "undo":
        drop(store, str(before.get("redo_bead") or ""), "the owner took the redo back")
    waiting = sum(1 for x in items if x.get("status") not in ("good", "redo"))
    if verdict == "undo" and shown.status == "closed":
        store.update(shown.id, BeadPatch(status="open"))
    elif verdict != "undo" and not waiting:
        store.close(shown.id, "the owner answered every look")
    return str(next(x for x in items if x.get("id") == item)["status"]), ""


def drop(store: Beads, bead: str, why: str = "the answer could not be saved") -> None:
    """Close a follow-up bead that no answer points at (a failed save, an undone redo)."""
    if is_bead_id(bead):
        with contextlib.suppress(BdFailure):
            store.close(bead, why)


def file_redo(store: Beads, look_bead: str, e: dict[str, Any], note: str) -> BeadId:
    """The follow-up bead of a redo: the owner's note and the pictures, related to the bead the look came from. -> its id."""
    pics = "\n".join("- {} ({})".format(s["path"], s.get("role") or "after") for s in e.get("shots") or [])
    desc = 'The owner looked at "{}" ({}) and asked for a change.\n\nWhat to change:\n{}\n\nPictures:\n{}\n'.format(
        e.get("title") or e.get("id"), e.get("bead") or look_bead, note, pics or "(none)")
    made = store.create(NewBead(title="Redo look: " + (e.get("title") or e.get("id") or look_bead)[:90], priority=2, description=desc,
                                deps=["related:" + (e.get("bead") or look_bead)]))
    with contextlib.suppress(BdFailure):  # the bead and its description already carry the note
        store.update(made, BeadPatch(metadata={"looks": {"from": e.get("id"), "shots": e.get("shots") or [], "note": note}}))
    return made


