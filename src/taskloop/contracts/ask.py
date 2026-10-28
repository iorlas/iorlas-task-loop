"""Ask: a question the engine puts to the owner (asks/<bead>.json, v2), and the owner's answer. Every field is typed: the page and the
engine read fields, never prose."""
from dataclasses import field
from typing import ClassVar, Literal

from taskloop.contracts.codec import record
from taskloop.contracts.enums import AskClass, AskKind, AskStatus, WhyCode

AskAction = Literal["rerun", "confirm", "split", "text"]


@record
class AskOption:
    """One way out: what it does next, what it costs, and the typed answer a click files. `edit`: the click fills the text box."""

    label: str
    consequence: str
    action: AskAction = "text"
    text: str = ""
    cost: str = ""
    recommended: bool = False
    edit: bool = False


@record
class AskAnswer:
    """What the owner chose; the dashboard and `tl` write it, the next run consumes it."""

    action: AskAction
    text: str = ""
    t: float = 0.0
    by: str = ""


@record
class BudgetLine:
    step: str
    minutes: float
    rounds: int = 0
    usd: float = 0.0


@record
class ReplanLine:
    n: int
    why: str


@record
class AskDetail:
    """The structured part of an ask, so a page renders it without parsing prose. `text`: the worker's own words, whole."""

    budget: list[BudgetLine] = field(default_factory=list)
    replans: list[ReplanLine] = field(default_factory=list)
    text: str = ""


@record
class Ask:
    V: ClassVar[int] = 2
    id: str
    n: int
    bead: str
    kind: AskKind
    ask_class: AskClass = field(metadata={"name": "class"})
    decision: str
    run: str
    t: float
    status: AskStatus
    tried: list[str] = field(default_factory=list)
    options: list[AskOption] = field(default_factory=list)
    detail: AskDetail = field(default_factory=AskDetail)
    why_code: WhyCode | None = None
    why: str = ""
    parks_at: float | None = None
    brief_hash: str = ""
    repo: str = ""
    title: str = ""
    answer: AskAnswer | None = None
    answered: float | None = None
    consumed: float | None = None
    closed_why: str = ""
