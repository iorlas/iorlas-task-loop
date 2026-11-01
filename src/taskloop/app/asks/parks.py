"""Park as a state transition (tl-7y6.7.3), on the config dir: the loop's pick and run-task's entry ask `gate`; a run's close tells `ended`.
The rule itself is domain/beads/park.py."""
import time
from collections.abc import Callable
from random import random

from taskloop.app.asks import intake
from taskloop.contracts.ask import Ask
from taskloop.contracts.bead import Bead
from taskloop.contracts.kinds import ASKS, FINISH, PAUSES, Kind
from taskloop.contracts.loop import Skip
from taskloop.contracts.parks import Park, ParkStore
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore
from taskloop.domain.beads import park
from taskloop.domain.lanes import pauses


def answered(ask: Ask | None) -> bool:
    return ask is not None and ask.consumed is None and ask.answer is not None


def gate(cfg: ConfigDir, b: Bead, *, fresh: bool = False, now: float | None = None) -> park.Verdict | None:
    """Why the bead is not taken now, None when it may be."""
    stamp = time.time() if now is None else now
    rec = ParkStore(cfg).get(b.id)
    if rec and rec.reason == Kind.OWNER_PARK.value and not intake.held(b.metadata, stamp):
        return None  # releasing the owner's hold is this park's explicit wake rule
    return park.verdict(rec, b, fresh=fresh, answered=answered(AskStore.at(cfg).get(b.id)), now=stamp)


def skip_of(cfg: ConfigDir, b: Bead, *, now: float | None = None) -> Skip | None:
    """The gate as the queue's typed skip."""
    v = gate(cfg, b, now=now)
    rec = ParkStore(cfg).get(b.id)
    return Skip(why=v.why, kind=v.kind, until=rec.retry_at if rec and rec.retry_at else None) if v else None


def entering(cfg: ConfigDir, b: Bead) -> None:
    """A run goes on from the owner's answer: the count of runs on this text starts again."""
    if answered(AskStore.at(cfg).get(b.id)):
        ParkStore(cfg).drop(b.id)


def paused(cfg: ConfigDir, b: Bead, kind: Kind, run: str, now: float, *, reason: str = "",
           not_before: float = 0.0, draw: Callable[[], float] = random) -> Park | None:
    """File a pause's wake, including an empty plan's explicit owner wake."""
    if kind is Kind.NOOP:
        reason = "plan_noop"
    reason = reason or kind.value
    if kind is not Kind.NOOP and (kind not in PAUSES or pauses.rule(reason).permanence != "transient"):
        return None
    store = ParkStore(cfg)
    old = store.get(b.id)
    rec = pauses.after_pause(old, b, run, now, reason, draw, not_before)
    store.put(rec)
    return rec


def ended(cfg: ConfigDir, b: Bead, kind: Kind, run: str, now: float) -> None:
    """A run's close: one more run on this text when it ended on a question, no record once the bead is done."""
    store = ParkStore(cfg)
    if kind in FINISH:
        store.drop(b.id)
    elif kind in ASKS:
        store.put(park.after_question(store.get(b.id), b, run, now))
