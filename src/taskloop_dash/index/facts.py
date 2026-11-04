"""Persisted run state, never log history. Beats retain only their latest value."""

import json

from taskloop.contracts import log, wire
from taskloop.contracts.wire import Rec
from taskloop_dash.views.runfacts import FoldState, fold


class Facts(Rec):
    state: FoldState = FoldState()
    beat: log.Beat | None = None
    has_log: bool = False
    log_mtime: float = 0.0


def decode(raw: str | None) -> Facts:
    return wire.load(Facts, raw) if raw else Facts()


def encode(facts: Facts) -> str:
    return json.dumps(wire.builtins(facts), separators=(",", ":"))


def append(facts: Facts, rows: list[log.EngineLog]) -> Facts:
    beats = [r for r in rows if isinstance(r, log.Beat)]
    return facts.replace(state=fold(facts.state, rows), beat=beats[-1] if beats else facts.beat)
