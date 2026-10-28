"""An ask as the owner reads it, built from the record's fields: no parsing of prose, no pattern matching."""
from typing import Final

from taskloop.contracts.ask import Ask, AskAnswer, BudgetLine

KIND_TITLE: Final = {"decision": "Decision needed", "stuck": "Stuck: direction needed", "budget": "Over its time limit",
              "ticket": "The bead needs sorting out"}
SPLIT_WORDS = "split this bead: keep what is done as this bead and file the rest as new beads"
DETAIL_CAP = 1200


def clip(text: str, n: int) -> str:
    """At most n characters, cut at a word and marked."""
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    return text[: n - 1].rsplit(" ", 1)[0].rstrip(",;:( ") + "…"


def budget_line(b: BudgetLine) -> str:
    rounds = f" ({b.rounds} round{'' if b.rounds == 1 else 's'})" if b.rounds else ""
    return f"{b.step} took {round(b.minutes)} min{rounds}"


def bullets(ask: Ask) -> list[str]:
    """What happened: the tried lines, then the structured detail (where the minutes went, why each plan was redone)."""
    out = list(ask.tried)
    out += [budget_line(b) for b in ask.detail.budget]
    out += [f"plan {r.n}: {r.why}" for r in ask.detail.replans]
    return out


def markdown(ask: Ask) -> str:
    """The card's text: the decision as the headline, what happened, and the engine's own words when it has more."""
    lines = [f"**{ask.decision}**"]
    shown = bullets(ask)
    if shown:
        lines += ["", "**What happened**"] + [f"- {b}" for b in shown]
    more = ask.detail.text.strip()
    if more and more != ask.decision:
        lines += ["", "**Details**", clip(more, DETAIL_CAP)]
    return "\n".join(lines)


def headline(ask: Ask) -> str:
    return f"{KIND_TITLE[ask.kind.value]}: {ask.decision}"


def comment(ask: Ask) -> str:
    """The note left on the bead when an ask is raised: for people reading the bead, never read back by the engine."""
    opts = "; ".join("{}{}: {}".format("*" if o.recommended else "", o.label, o.consequence) for o in ask.options)
    return f"Ask (engine) {ask.id} ({ask.kind.value}): {ask.decision} Options: {opts}"


def words(answer: AskAnswer | None) -> str:
    """What an answer says the work should do, for a planner or writer: the owner's text, or the split instruction; a bare
    rerun or confirm says nothing."""
    if answer is None:
        return ""
    if answer.action == "split":
        return SPLIT_WORDS
    return answer.text.strip() if answer.action == "text" else ""
