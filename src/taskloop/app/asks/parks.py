"""Park as a state transition (tl-7y6.7.3), on the config dir: the loop's pick and run-task's entry ask `gate`; a run's close tells `ended`.
The rule itself is domain/beads/park.py."""
from taskloop.contracts.ask import Ask
from taskloop.contracts.bead import Bead
from taskloop.contracts.kinds import ASKS, FINISH, Kind
from taskloop.contracts.loop import Skip
from taskloop.contracts.parks import ParkStore
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore
from taskloop.domain.beads import park


def answered(ask: Ask | None) -> bool:
    return ask is not None and ask.consumed is None and ask.answer is not None


def gate(cfg: ConfigDir, b: Bead, *, fresh: bool = False) -> park.Verdict | None:
    """Why the bead is not taken now, None when it may be."""
    return park.verdict(ParkStore(cfg).get(b.id), b, fresh=fresh, answered=answered(AskStore.at(cfg).get(b.id)))


def skip_of(cfg: ConfigDir, b: Bead) -> Skip | None:
    """The gate as the queue's typed skip."""
    v = gate(cfg, b)
    return Skip(why=v.why, kind=v.kind) if v else None


def entering(cfg: ConfigDir, b: Bead) -> None:
    """A run goes on from the owner's answer: the count of runs on this text starts again."""
    if answered(AskStore.at(cfg).get(b.id)):
        ParkStore(cfg).drop(b.id)


def ended(cfg: ConfigDir, b: Bead, kind: Kind, run: str, now: float) -> None:
    """A run's close: one more run on this text when it ended on a question, no record once the bead is done."""
    store = ParkStore(cfg)
    if kind in FINISH:
        store.drop(b.id)
    elif kind in ASKS:
        store.put(park.after_question(store.get(b.id), b, run, now))
