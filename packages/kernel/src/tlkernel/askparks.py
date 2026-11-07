"""Park as a state transition (tl-7y6.7.3), on the config dir: the loop's pick and run-task's entry ask `gate`; a run's close tells `ended`.
The rule itself is tlkernel/beadpark.py."""
from collections.abc import Callable

from tlkernel import beadpark as park
from tlkernel import holds as hold
from tlkernel import lanepauses as pauses
from tlkernel.ask import Ask
from tlkernel.askport import AskReader
from tlkernel.bead import Bead
from tlkernel.delegate import Permanence
from tlkernel.ids import BeadId
from tlkernel.kinds import ASKS, FINISH, PAUSES, Kind
from tlkernel.loop import Skip
from tlkernel.parks import Park, ParkStore
from tlkernel.paths import ConfigDir
from tlkernel.pausereasons import Producer


def answered(ask: Ask | None) -> bool:
    return ask is not None and ask.consumed is None and ask.answer is not None


def gate(asks: AskReader, cfg: ConfigDir, b: Bead, *, fresh: bool = False,
         now: float, store: Callable[[ConfigDir], ParkStore]) -> park.Verdict | None:
    """Why the bead is not taken now, None when it may be."""
    rec = store(cfg).get(b.id)
    if rec and rec.reason == Kind.OWNER_PARK.value and not hold.held(b.metadata, now):
        return None  # releasing the owner's hold is this park's explicit wake rule
    return park.verdict(rec, b, fresh=fresh, answered=answered(asks.get(b.id)), now=now)


def skip_of(asks: AskReader, cfg: ConfigDir, b: Bead, *, now: float, store: Callable[[ConfigDir], ParkStore]) -> Skip | None:
    """The gate as the queue's typed skip."""
    v = gate(asks, cfg, b, now=now, store=store)
    rec = store(cfg).get(b.id)
    return Skip(why=v.why, kind=v.kind, until=rec.retry_at if rec and rec.retry_at else None) if v else None


def entering(asks: AskReader, cfg: ConfigDir, b: Bead, *, store: Callable[[ConfigDir], ParkStore]) -> None:
    """A run goes on from the owner's answer: the count of runs on this text starts again."""
    if answered(asks.get(b.id)):
        store(cfg).drop(b.id)


def paused(cfg: ConfigDir, b: Bead, kind: Kind, run: str, now: float, *, reason: str = "",
           not_before: float = 0.0, draw: Callable[[], float], fingerprint: str = "",
           producer: Producer | None = None, permanence: Permanence | None = None, store: Callable[[ConfigDir], ParkStore]) -> Park:
    """File a pause's wake, including an empty plan's explicit owner wake."""
    if kind is Kind.NOOP:
        reason = "plan_noop"
    reason = reason or kind.value
    if kind is not Kind.NOOP and kind not in PAUSES:
        raise ValueError(f"no park wake for kind {kind}")
    return store(cfg).change(b.id, lambda old: pauses.after_pause(old, b, run, now, reason, draw, not_before,
                                                               fingerprint=fingerprint, producer=producer, permanence=permanence))


def profile_ahead(cfg: ConfigDir, b: Bead, run: str, now: float, why: str, *, store: Callable[[ConfigDir], ParkStore]) -> None:
    """The loop's pick found the bead's profile ahead of this checkout (or its setup on its own tree): park it for a short, random time."""
    store(cfg).change(b.id, lambda old: pauses.after_pause(old, b, run, now, why, lambda: 0.5))


def finished(cfg: ConfigDir, b: BeadId, *, store: Callable[[ConfigDir], ParkStore]) -> None:
    """A stage run that finished the bead: no park is kept."""
    store(cfg).drop(b)


def ended(cfg: ConfigDir, b: Bead, kind: Kind, run: str, now: float, *, store: Callable[[ConfigDir], ParkStore]) -> None:
    """A run's close: one more run on this text when it ended on a question, no record once the bead is done."""
    parks = store(cfg)
    if kind in FINISH:
        parks.drop(b.id)
    elif kind in ASKS:
        parks.change(b.id, lambda old: park.after_question(old, b, run, now))
