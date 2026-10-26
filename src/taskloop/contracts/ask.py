"""Ask: a question the engine puts to the owner (asks/<bead>.json, v2), and the owner's answer."""
from dataclasses import field
from typing import ClassVar, Literal

from taskloop.contracts.codec import record
from taskloop.contracts.enums import AskKind, AskStatus, WhyCode


@record
class AskOption:
    label: str
    cost: str = ""
    answer: str = ""
    recommended: bool = False


@record
class AskAnswer:
    """What the owner chose; the dashboard writes it, the next run consumes it."""

    action: Literal["rerun", "amend", "confirm", "text"]
    text: str = ""
    t: float = 0.0
    by: str = ""


@record
class BudgetLine:
    step: str
    minutes: float
    usd: float = 0.0


@record
class ReplanLine:
    n: int
    why: str


@record
class AskDetail:
    """The structured part of an ask, so the dashboard renders it without parsing prose."""

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
    question: str
    run: str
    t: float
    status: AskStatus
    detail: AskDetail | None = None
    why_code: WhyCode | None = None
    why: str = ""
    parks_at: float | None = None
    brief_hash: str = ""
    options: list[AskOption] = field(default_factory=list)
    repo: str = ""
    title: str = ""
    answer: AskAnswer | None = None
    answered: float | None = None
