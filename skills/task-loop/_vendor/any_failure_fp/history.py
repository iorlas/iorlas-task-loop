"""What a history of earlier failures says about the next one: a storm, a streak, a repeat. Pure; no clock."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


@dataclass(frozen=True)
class Event:
    """One earlier failure: who (`key`), what class (`kind`), which cause (`fp`), when (`t`, epoch seconds)."""

    key: str
    fp: str
    t: float
    kind: str = ""


@dataclass(frozen=True)
class Trip:
    fp: str
    keys: tuple[str, ...]
    t: float


def trip(
    history: Sequence[Event],
    key: str,
    fp: str,
    now: float,
    *,
    window_s: float,
    min_keys: int,
    count: Callable[[Event], bool] | None = None,
) -> Trip | None:
    """The storm this failure causes, or None: `fp` on at least `min_keys` distinct keys inside `window_s`.

    (`key`, `fp`) is the failure being recorded and counts itself. `count` narrows which earlier events may count.
    """
    cut = now - window_s
    keys = {key}
    for e in history:
        if e.fp == fp and e.t >= cut and (count is None or count(e)):
            keys.add(e.key)
    if len(keys) < min_keys:
        return None
    return Trip(fp, tuple(sorted(keys)), now)


def streak(history: Sequence[Event], key: str, fp: str, stop: Callable[[Event], bool]) -> int:
    """How many failures with `fp` `key` has had since its last `stop` event, counting the one being recorded.

    Walks `key`'s events newest first; a different fingerprint is skipped, not a break.
    """
    same = 1
    for e in reversed([e for e in history if e.key == key]):
        if stop(e):
            break
        if e.fp == fp:
            same += 1
    return same


def seen_within(history: Sequence[Event], key: str, kind: str, fp: str, *, now: float, window_s: float) -> bool:
    """Whether (`key`, `kind`, `fp`) was already recorded within `window_s` of `now`: the dedupe of a repeated comment."""
    cut = now - window_s
    return any(e.key == key and e.kind == kind and e.fp == fp and e.t >= cut for e in history)
