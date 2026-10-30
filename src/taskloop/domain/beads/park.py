"""Park as a state transition (tl-7y6.7.3): a bead whose run ended on a question is taken again only when its text changed. Pure.

`verdict` is the one rule the loop (at the pick) and run-task (at the entry) share. The text is title, description and acceptance
criteria: comments, labels and the engine's own lines are not the owner changing the bead."""
import hashlib
from dataclasses import dataclass
from typing import Final, Literal

from taskloop.contracts.bead import Bead
from taskloop.contracts.parks import Park

HARD_AT: Final = 2  # runs on one text after which nothing takes the bead again, --fresh included: the next would be the 3rd


def text_hash(b: Bead) -> str:
    """The bead's own words, as one hash; a field boundary is part of it (moving a line from the title to the description changes it)."""
    parts = (b.title, b.description, b.acceptance_criteria)
    return hashlib.sha1("\x00".join(p.strip() for p in parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Verdict:
    kind: Literal["parked", "capped"]  # parked: --fresh or an answer lets it run; capped: only a change of the text does
    why: str


def verdict(rec: Park | None, b: Bead, *, fresh: bool = False, answered: bool = False) -> Verdict | None:
    """Why the bead is not taken now, None when it may be. `answered`: the owner filed an answer on its ask (new input: a run goes
    on from it, and the count starts again), `fresh`: the owner asked for a new run by hand."""
    if rec is None or rec.hash != text_hash(b) or answered:
        return None
    if rec.runs >= HARD_AT:
        return Verdict("capped", f"{rec.runs} runs ended on a question with this text: change the description or acceptance criteria")
    if fresh:
        return None
    return Verdict("parked", "a run ended on a question and the bead text is unchanged: change it, answer the ask, or run it with --fresh")


def after_question(rec: Park | None, b: Bead, run: str, now: float) -> Park:
    """The record after a run ended on a question: one more on the same text, the first on a new one."""
    h = text_hash(b)
    if rec is not None and rec.run == run:
        return rec
    runs = rec.runs + 1 if rec is not None and rec.hash == h else 1
    return Park(bead=b.id, hash=h, runs=runs, run=run, t=now)
