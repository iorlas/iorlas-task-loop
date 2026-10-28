"""Raising an ask and starting from an answered one: the engine's two moments with the owner. Pure of bd and git except for the
queue label, which goes through the Beads port."""
from dataclasses import dataclass

from taskloop.contracts.ask import Ask
from taskloop.contracts.enums import AskStatus, WhyCode
from taskloop.contracts.ports import BdFailure, BeadPatch, Beads
from taskloop.contracts.stores import HAD_PICK, AskStore
from taskloop.domain.asks.lint import lint
from taskloop.domain.asks.spec import AskSpec

PARK_AFTER_S = 3 * 86400
WHY_CAP = 4000


@dataclass(frozen=True)
class Asking:
    """Where and when an ask is raised."""

    bead: str
    run: str
    brief_hash: str
    repo: str
    title: str
    now: float
    why: str = ""
    why_code: WhyCode | None = None


def build(spec: AskSpec, n: int, at: Asking) -> Ask:
    return Ask(id=f"{at.bead}-{n}", n=n, bead=at.bead, kind=spec.kind, ask_class=spec.ask_class, decision=spec.decision, run=at.run,
               t=at.now, status=AskStatus.OPEN, tried=list(spec.tried), options=list(spec.options), detail=spec.detail,
               why_code=at.why_code, why=at.why[:WHY_CAP], parks_at=at.now + PARK_AFTER_S, brief_hash=at.brief_hash, repo=at.repo,
               title=at.title[:200])


def raise_ask(asks: AskStore, spec: AskSpec, at: Asking) -> tuple[Ask | None, list[str]]:
    """File the ask and return it; (None, the broken lint rules) when it is not one an owner can answer: nothing is written then,
    and no prose ask takes its place."""
    ask = build(spec, asks.next_n(at.bead), at)
    problems = lint(ask)
    if problems:
        return None, problems
    asks.put(ask)
    return ask, []


def waiting_line(ask: Ask) -> str:
    return f"waiting: for the owner's answer to ask {ask.id} ({ask.kind.value}): {ask.decision}"


def check(asks: AskStore, bead: str, brief_hash: str, fresh: bool, now: float) -> tuple[str, Ask | None]:
    """The run starts. -> ("none", None): no ask is open; ("wait", ask): still open and the bead unchanged, so the run waits;
    ("answer", ask): the owner answered it (or changed the bead), so it is consumed and the run goes on from it."""
    ask = asks.get(bead)
    if ask is None or ask.consumed is not None or ask.status not in (AskStatus.OPEN, AskStatus.PARKED, AskStatus.ANSWERED):
        return "none", None
    if ask.answer is None and ask.brief_hash == brief_hash and not fresh:
        return "wait", ask
    return "answer", asks.consume(bead, now)


def leave_queue(store: Beads, bead: str, pick: str, info: str) -> str:
    """A decision or ticket ask means the bead lacks what it needs to be done unattended: the pick label goes (no runner takes it
    again) and needs-info comes. Answering does not put it back: the owner relabels it, since an answer can split the bead."""
    try:
        shown = store.show(bead)
        if not pick or not shown or pick not in shown.labels:
            return ""
        store.remove_label(bead, pick)
        store.update(bead, BeadPatch(set_metadata={HAD_PICK: pick}))  # typed: only a label the bead had is ever given back
        if info:
            store.add_label(bead, info)
    except BdFailure:
        return ""
    return "\n(Out of the {} queue: label {} removed{}; relabel it {} once it can be done unattended.)".format(
        pick, pick, f", {info} added" if info else "", pick)


def problems(spec: AskSpec) -> list[str]:
    """The lint rules this spec breaks as an ask: what the close checks before it files anything."""
    return lint(build(spec, 1, Asking(bead="-", run="", brief_hash="", repo="", title="", now=0.0)))
