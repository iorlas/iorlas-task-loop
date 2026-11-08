"""Make it stick: what the owner turns an answered ask into (dash-spec 5.3). Each outcome has an effect through a typed port and one
ledger row. The ADR is landed through a bead (`docs/adr/NNNN-title.md`, contracts/adrfiles.py): the engine and `tl` never write into a
checkout, so the outcome files the bead and an account lands the file; a factory bead is filed in the task-loop repo; a fix amends the
bead's own text; demote and once record the outcome only.

`Stick.REF` links the ask to a decision already in force (the one its repeat key matched, or the id named in `text`)."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never

from tlkernel import adrfiles
from tlkernel.adrs import AdrStore, is_adr_id
from tlkernel.beadsport import BeadPatch, BeadQuery, Beads, NewBead
from tlkernel.dash import Stick
from tlkernel.ledger import LedgerEntry

FACTORY_LABEL = "factory"
TITLE_CAP = 200
TEXT_CAP = 2000


@dataclass(frozen=True)
class Effects:
    """The ports an outcome acts through: the repo's ADR store, the task-loop repo's tracker (None when none is registered), and the
    tracker of the ask's own repo."""

    adrs: Callable[[str], AdrStore] | None
    factory: Callable[[], Beads | None] | None
    store: Beads


def draft(raised: LedgerEntry, answer: str) -> str:
    """An ADR's text when the owner wrote none: the question and the answer it got."""
    return f"{raised.question} Decided: {answer or '(go on as planned)'}"[:TEXT_CAP]


def decide(fx: Effects, raised: LedgerEntry, answered: LedgerEntry, outcome: Stick, text: str, by: str, now: float) -> tuple[str, str]:
    """Do the outcome's effect. -> (the reference it made: an ADR id, a bead id, or "", and why it could not be done: "" when it was)."""
    text = text.strip()
    if outcome is Stick.ADR:
        return adr(fx, raised, answered, text, by, now)
    if outcome is Stick.REF:
        return ref(fx, raised, text)
    if outcome is Stick.FACTORY:
        return factory(fx, raised, answered, text)
    if outcome is Stick.FIX:
        return fix(fx, raised, answered, text)
    if outcome is Stick.DEMOTE or outcome is Stick.ONCE:  # no effect beyond the ledger's own record
        return "", ""
    assert_never(outcome)


def adr(fx: Effects, raised: LedgerEntry, answered: LedgerEntry, text: str, by: str, now: float) -> tuple[str, str]:
    """File the bead that lands the ADR. -> its id (the ADR's number is the file's, taken when it lands)."""
    if fx.adrs is not None:
        have = next((a for a in fx.adrs(raised.repo).all() if a.ask == raised.ask and a.retired_t is None), None)
        if have is not None:
            return have.id, ""  # landed already: one decision per ask
    marker = f"- Ask: {raised.ask}\n"
    pending = next((b for b in fx.store.find(BeadQuery(label=adrfiles.LABEL)) if marker in b.description), None)
    if pending is not None:
        return pending.id, ""  # asked twice: the bead that lands it is already open
    decision = text[:TEXT_CAP] or draft(raised, answered.answer)
    body = adrfiles.template(raised.ask, raised.bead, raised.key, raised.question, answered.answer, decision, by, now)
    title = f"ADR: {adrfiles.title_of(decision)}"[:TITLE_CAP]
    return fx.store.create(NewBead(title=title, description=body, labels=[adrfiles.LABEL], no_inherit_labels=True)), ""


def retire(store: Beads, adr: str) -> str:
    """File the bead that retires a decision in force (its file's Status line); a second ask finds the one open. -> its id."""
    title = f"Retire {adr}"
    pending = next((b for b in store.find(BeadQuery(label=adrfiles.LABEL)) if b.title == title), None)
    if pending is not None:
        return pending.id
    body = (f"Retire {adr}: in its `{adrfiles.DIR}` file set `- Status: retired` and add the lines `- Retired-by: <who>` and "
            f"`- Retired-at: <epoch seconds>`. Leave the sections as they are.")
    return store.create(NewBead(title=title, description=body, labels=[adrfiles.LABEL], no_inherit_labels=True))


def ref(fx: Effects, raised: LedgerEntry, text: str) -> tuple[str, str]:
    """Link the ask to a decision in force: the link is the ledger row's `outcome_ref`, the ADR file is not edited."""
    if fx.adrs is None:
        return "", "there is no decision store here"
    store = fx.adrs(raised.repo)
    words = text.split()
    named = words[0] if words else next((s.id for s in raised.similar if s.kind == "adr"), "")
    found = store.get(named) if is_adr_id(named) else None
    if found is None or found.retired_t is not None:
        return "", "name a decision in force (ADR-n) to link this ask to" if not named else f"{named} is not a decision of this repo"
    return found.id, ""


def factory(fx: Effects, raised: LedgerEntry, answered: LedgerEntry, text: str) -> tuple[str, str]:
    tracker = fx.factory() if fx.factory is not None else None
    if tracker is None:
        return "", "no task-loop repo is registered to file the bead in"
    marker = f"Filed from the answer to ask {raised.ask} of "
    pending = next((b for b in tracker.find(BeadQuery(label=FACTORY_LABEL, include_closed=True)) if b.description.startswith(marker)), None)
    if pending is not None:
        return pending.id, ""  # the ledger write failed after the bead was filed, or the tap came twice: one bead per ask
    title = (text.splitlines() or [""])[0].strip() or f"factory: {raised.question}"
    body = (f"{marker}{raised.bead}.\n\nQuestion: {raised.question}\n"
            f"Answer: {answered.answer or '(none)'}" + (f"\n\n{text}" if "\n" in text or len(text) > TITLE_CAP else ""))
    return tracker.create(NewBead(title=title[:TITLE_CAP], description=body[:TEXT_CAP], labels=[FACTORY_LABEL], no_inherit_labels=True)), ""


def fix(fx: Effects, raised: LedgerEntry, answered: LedgerEntry, text: str) -> tuple[str, str]:
    """The bead's text gets the owner's clarification appended, so the brief changes and the plan runs again."""
    if not text:
        return "", "say what the bead text should add"
    shown = fx.store.show(raised.bead)
    if shown is None:
        return "", "the bead does not exist"
    note = f"Clarified by the owner (answer to ask {raised.ask}): {text}"
    fx.store.update(raised.bead, BeadPatch(description=f"{shown.description.rstrip()}\n\n{note}".strip()))
    return raised.bead, ""
