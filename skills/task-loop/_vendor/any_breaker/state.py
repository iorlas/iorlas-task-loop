"""What the fold remembers, as plain data a checkpoint can carry through JSON."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

KEEP_FAILURES = 3


@dataclass
class Strike:
    ts: float
    kind: str
    fp: str
    source: str | None


@dataclass
class Failure:
    ts: float
    kind: str
    note: str


@dataclass
class KeyState:
    streak: list[Strike] = field(default_factory=list)
    rung: int = 0
    until: float = 0.0
    kind: str | None = None
    fp: str | None = None
    evidence: str = ""
    source: str | None = None
    recent: list[Failure] = field(default_factory=list)
    last_ok: float = 0.0


@dataclass
class OutState:
    kind: str
    until: float
    source: str
    evidence: str
    ts: float


@dataclass
class State:
    """`ts` is the newest fact folded: a fact at or before it is already in. `keys` counts failures, `outs` holds whole-key outs."""

    ts: float = 0.0
    keys: dict[str, KeyState] = field(default_factory=dict)
    outs: dict[str, OutState] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> State:
        keys = {k: _key_of(v) for k, v in d.get("keys", {}).items()}
        return cls(ts=d.get("ts", 0.0), keys=keys, outs={k: OutState(**v) for k, v in d.get("outs", {}).items()})


def _key_of(v: dict[str, Any]) -> KeyState:
    return KeyState(
        streak=[Strike(**s) for s in v.get("streak", [])],
        rung=v.get("rung", 0),
        until=v.get("until", 0.0),
        kind=v.get("kind"),
        fp=v.get("fp"),
        evidence=v.get("evidence", ""),
        source=v.get("source"),
        recent=[Failure(**f) for f in v.get("recent", [])],
        last_ok=v.get("last_ok", 0.0),
    )
