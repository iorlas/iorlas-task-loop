"""The ask ledger and the decision store as typed records. The ledger (ask-ledger.jsonl) is append-only and never swept: one row per
transition of an ask, so history outlives the one-file-per-bead ask document. An ADR is a decision of the owner that the plan stage
reads; its uses (a plan cited it) are rows of their own, so a reuse counter never rewrites the ADR."""
from typing import ClassVar, Literal

import msgspec

from taskloop.contracts.ask import CauseBy, SimilarRef
from taskloop.contracts.dash import OwnerCause, Stick
from taskloop.contracts.wire import Rec

LedgerEvent = Literal["raise", "answer", "consume", "close", "withdraw", "cause", "stick", "demote"]
LEDGER_EVENTS = ("raise", "answer", "consume", "close", "withdraw", "cause", "stick", "demote")


class LedgerEntry(Rec):
    """One transition of an ask. `question`, `key`, `repo` and `similar` are set at raise; `cause` and `outcome` are what was known at
    this row (the newest row of an ask says the current cause and outcome)."""

    V: ClassVar[int] = 1
    t: float
    event: LedgerEvent
    ask: str
    bead: str
    repo: str = ""
    question: str = ""
    key: str = ""
    blocking: bool = True
    cause: OwnerCause = OwnerCause.UNKNOWN
    cause_by: CauseBy = "agent"
    answer: str = ""
    outcome: Stick | None = None
    outcome_ref: str = ""
    similar: list[SimilarRef] = msgspec.field(default_factory=list)
    why: str = ""


class Adr(Rec):
    """A decision in force for one repo (adrs/<repo key>/<id>.json): the owner's answer to `ask`, worded for the plan stage."""

    V: ClassVar[int] = 1
    id: str
    n: int
    repo: str
    text: str
    question: str
    answer: str
    ask: str
    bead: str
    key: str
    t: float
    by: str = ""
    refs: list[str] = msgspec.field(default_factory=list)
    retired_by: str = ""  # who retired it (prune); a retired decision stays in the store but is no longer in force
    retired_t: float | None = None


class AdrUse(Rec):
    """A plan of `bead` relied on the ADR (it named its id in `PlanAnswer.cited`)."""

    V: ClassVar[int] = 1
    adr: str
    bead: str
    run: str
    t: float
