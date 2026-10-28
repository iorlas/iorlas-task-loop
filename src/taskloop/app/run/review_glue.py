"""The one place the engine's review and verify attributes meet `RunState.review` (a `ReviewState`, opaque to the run state)."""

import dataclasses
from typing import Any

from taskloop.contracts.review import ReviewState, Unchecked, Unverified


def known[T](cls: type[T], items: list[dict[str, Any]]) -> list[T]:
    names = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    return [cls(**{k: v for k, v in x.items() if k in names}) for x in items]


def review_of(e: Any) -> ReviewState:
    return ReviewState(unchecked=known(Unchecked, e.unchecked), unverified=known(Unverified, e.unverified), filed=list(e.filed),
                       unfiled=list(e.unfiled))


def apply_review(e: Any, review: ReviewState, *, unchecked: bool, late: bool = False) -> None:
    """A resume hands back what review and verify left: the unverified items always, the unchecked ones only to a run that lands, the
    follow-ups filed or refused only from a checkpoint this engine left (`late`)."""
    if late:
        e.filed, e.unfiled = list(review.filed), list(review.unfiled)
    e.unverified = [dataclasses.asdict(u) for u in review.unverified]
    if unchecked:
        e.unchecked = [dataclasses.asdict(u) for u in review.unchecked]
