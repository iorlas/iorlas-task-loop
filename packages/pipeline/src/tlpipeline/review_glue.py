"""The one place the engine's review and verify attributes meet `RunState.review` (a `ReviewState`, opaque to the run state)."""

from typing import Protocol

from tlkernel import wire
from tlkernel.review import ReviewState, Unchecked, Unfiled, Unverified
from tlkernel.wire import Rec


class ReviewLists(Protocol):
    unchecked: list[dict[str, object]]
    unverified: list[dict[str, object]]


class ReviewOwner(Protocol):
    @property
    def review(self) -> ReviewLists: ...

    filed: list[str]
    unfiled: list[Unfiled]


def known[T: Rec](cls: type[T], items: list[dict[str, object]]) -> list[T]:
    names = set(wire.names(cls))
    return [cls(**{k: v for k, v in x.items() if k in names}) for x in items]


def review_of(e: ReviewOwner) -> ReviewState:
    return ReviewState(unchecked=known(Unchecked, e.review.unchecked), unverified=known(Unverified, e.review.unverified),
                       filed=list(e.filed), unfiled=list(e.unfiled))


def apply_review(e: ReviewOwner, review: ReviewState, *, unchecked: bool, late: bool = False) -> None:
    """A resume hands back what review and verify left: the unverified items always, the unchecked ones only to a run that lands, the
    follow-ups filed or refused only from a checkpoint this engine left (`late`)."""
    if late:
        e.filed, e.unfiled = list(review.filed), list(review.unfiled)
    e.review.unverified = [u.to_dict() for u in review.unverified]
    if unchecked:
        e.review.unchecked = [u.to_dict() for u in review.unchecked]


class ReviewGlue:
    def __init__(self, host: ReviewOwner) -> None:
        self.host = host

    def apply(self, review: ReviewState, *, unchecked: bool, late: bool = False) -> None:
        apply_review(self.host, review, unchecked=unchecked, late=late)
