"""ReviewState: everything the review and verify steps keep that must survive a park and a resume, as ONE record.

The run state holds exactly this one field of the review/verify side and never reaches into it: `ReviewState.dump()` writes it,
`ReviewState.from_dump()` reads it back (a stale or foreign dump raises, and the caller starts afresh).

It holds the counters the caps read, what the last review says nobody checked, what the verify step settled and what it left for the
owner, and the follow-ups filed or refused by bd.
"""
from dataclasses import field
from typing import Any, ClassVar

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


@record
class ReviewState:
    V: ClassVar[int] = 1
    reviews: int = 0
    rounds: int = 0
    unchecked: list[Unchecked] = field(default_factory=list)
    unverified: list[Unverified] = field(default_factory=list)
    verified: list[Verified] = field(default_factory=list)
    filed: list[str] = field(default_factory=list)
    unfiled: list[Unfiled] = field(default_factory=list)

    def dump(self) -> dict[str, Any]:
        return to_json(self)

    @classmethod
    def from_dump(cls, data: Any) -> "ReviewState":
        return from_json(cls, data)
