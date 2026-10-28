"""ReviewState: everything the review and verify steps keep that must survive a park and a resume, as ONE record.

The run state holds exactly this one field of the review/verify side and never reaches into it: `ReviewState.dump()` writes it,
`ReviewState.from_dump()` reads it back (a stale or foreign dump raises, and the caller starts the review book afresh).

It holds the finding book (what the reviewers said, by id, with the axis, the severity and the confidence), the counters the caps
read, what the verify step settled and what it left, the follow-ups bd refused, and the digest a re-plan starts from.
"""
from dataclasses import field
from typing import Any, ClassVar, Literal

from taskloop.contracts.codec import from_json, record, to_json
from taskloop.contracts.trace import Verified


@record
class Unchecked:
    what: str
    kind: str = ""
    source: str = ""
    why: str = ""
    proof_round: bool = False


@record
class Unverified:
    what: str
    kind: str = ""
    why: str = ""
    source: str = ""


@record
class Unfiled:
    """A follow-up bd refused: kept here so none is lost or counted as filed."""

    title: str
    why: str


Axis = Literal["spec", "standards"]
Confidence = Literal["certain", "likely", "possible"]
FindingStatus = Literal["open", "claimed", "verified", "dropped"]


@record
class BookedFinding:
    """One review finding in the book: raised once, then claimed fixed by the writer, then verified or reopened by a later review."""

    fid: str
    stage: int
    round: int
    axis: Axis
    severity: Literal["high", "medium", "low"]
    confidence: Confidence
    category: str
    file: str
    line: int
    fix: str
    scenario: str = ""
    status: FindingStatus = "open"


@record
class VerifyResult:
    """The last verify pass: how many items each verdict took, and the fix rounds it spent."""

    settled: int = 0
    wrong: int = 0
    open: int = 0
    fixes: int = 0
    asked: bool = False


@record
class ReplanDigest:
    """What the next planner is told (the old plan's notes, the cause, the open findings, the accepted stages, the diff stat)."""

    cause: str = ""
    notes: str = ""
    accepted: list[str] = field(default_factory=list)
    open_findings: list[str] = field(default_factory=list)
    diff_stat: str = ""


@record
class ReviewState:
    V: ClassVar[int] = 1
    reviews: int = 0
    rounds: int = 0
    book: list[BookedFinding] = field(default_factory=list)
    seen_lows: list[str] = field(default_factory=list)
    unchecked: list[Unchecked] = field(default_factory=list)
    unverified: list[Unverified] = field(default_factory=list)
    verified: list[Verified] = field(default_factory=list)
    verify: VerifyResult | None = None
    filed: list[str] = field(default_factory=list)
    unfiled: list[Unfiled] = field(default_factory=list)
    replan: ReplanDigest | None = None

    def dump(self) -> dict[str, Any]:
        return to_json(self)

    @classmethod
    def from_dump(cls, data: Any) -> "ReviewState":
        return from_json(cls, data)
