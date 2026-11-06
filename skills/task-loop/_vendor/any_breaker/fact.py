"""The vocabulary of the fold: what happened (`Fact`) and the rules it is counted under (`Policy`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

OK = "ok"
RELEASE = "release"

_NO_RULES: Mapping[str, Rule] = MappingProxyType({})
_NO_OUTS: Mapping[str, Out] = MappingProxyType({})


@dataclass(frozen=True)
class Fact:
    """One thing that happened to `key` at `ts`. The consumer turns its own rows into facts; a row that is no fact is simply not passed.

    kind    OK (a call worked: ends an out and resets the ladder), RELEASE (the owner says the key is fine; with `prefix`, every key
            that starts with `key`), a kind named in `Policy.outs` (the key is out until a time), or any other word (a counted failure).
    source  who suffered it (a task id): `Rule.distinct` failures must come from this many different sources. None is one source.
    fp      the fingerprint that makes two failures the same failure; defaults to the kind.
    until   for an out: the vendor's own unlock time, when it gave one.
    """

    kind: str
    ts: float
    key: str
    fp: str | None = None
    source: str | None = None
    until: float | None = None
    note: str = ""
    prefix: bool = False


@dataclass(frozen=True)
class Rule:
    """How one failure kind is counted; a field left None takes the `Policy` default."""

    n: int | None = None
    window_s: float | None = None
    distinct: int | None = None


@dataclass(frozen=True)
class Out:
    """A kind that puts the whole key out at once. The wait is `Fact.until` when it is later than the fact, else `ts + wait_s`."""

    wait_s: float
    source: str = "guess"


@dataclass(frozen=True)
class Policy:
    """n same-fingerprint failures inside window_s, from `distinct` different sources, open the breaker for the next rung of `ladder_s`.
    The first launch after a rung ends is the canary: a success resets the ladder, a failure starts the next rung at once."""

    n: int = 3
    window_s: float = 600.0
    distinct: int = 1
    ladder_s: tuple[float, ...] = (900.0, 1800.0, 3600.0)
    rules: Mapping[str, Rule] = field(default_factory=lambda: _NO_RULES)
    outs: Mapping[str, Out] = field(default_factory=lambda: _NO_OUTS)

    def __post_init__(self) -> None:
        if not self.ladder_s:
            msg = "ladder_s needs at least one rung"
            raise ValueError(msg)

    def rule(self, kind: str) -> tuple[int, float, int]:
        r = self.rules.get(kind, Rule())
        return (
            self.n if r.n is None else r.n,
            self.window_s if r.window_s is None else r.window_s,
            self.distinct if r.distinct is None else r.distinct,
        )
