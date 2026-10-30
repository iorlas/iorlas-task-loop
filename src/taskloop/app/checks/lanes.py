"""Lanes: the steps of a round that name different lanes run at the same time, each lane's steps in order. The first red of any lane
cancels the others: a lane's running check is stopped through the Spawner (its own process tree, with the engine's usual stop and
grace), its queue for a resource lease ends, and its steps not yet begun are recorded as cancelled, never as a verdict. A stop of the
whole run (the halt) is passed to every lane the same way. Nothing of a cancelled lane is remembered as green."""
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from taskloop.app.checks.round import Cancel, Round
from taskloop.domain.checks.plan import CheckPlan, Step

POLL_S = 0.05  # how often the owner looks at the run's halt while the lanes run


class LaneHost(Protocol):
    def halt_point(self, when: bool = ..., wait: float = ...) -> None: ...


@dataclass
class Fail:
    """A lane that ended in an exception (a fault of the check, the run's stop): re-raised by the owner once every lane has ended."""

    lane: str
    error: BaseException


@dataclass
class Race:
    """Which lane went red first, and what stopped by it."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    first: str | None = None
    fails: list[Fail] = field(default_factory=list)


class Lanes:
    def __init__(self, host: LaneHost, step: Callable[[Step, int, Round], None],
                 drop: Callable[[Step, int, Round, str], None]) -> None:
        self.host, self.step, self.drop = host, step, drop

    def run(self, plan: CheckPlan, lanes: dict[str, list[int]], st: Round) -> Round:
        """Run every lane at once and fold what they decided into `st`, the results in plan order."""
        parts = {name: replace_round(st, Cancel()) for name in lanes}
        race = Race()
        threads = [threading.Thread(target=self._lane, args=(name, plan, idx, parts, race), name=f"lane-{name or 'default'}", daemon=True)
                   for name, idx in lanes.items()]
        for t in threads:
            t.start()
        try:
            pending = list(threads)
            while pending:
                pending[0].join(POLL_S)
                pending = [t for t in pending if t.is_alive()]
                self.host.halt_point()  # a stop of the run raises here: the lanes are cancelled below
        except BaseException:
            self._cancel(parts, "", "the run was stopped")
            for t in threads:
                t.join()
            raise
        if race.fails:
            raise race.fails[0].error
        return self._fold(st, parts, race.first or "")

    def _lane(self, name: str, plan: CheckPlan, idx: list[int], parts: dict[str, Round], race: Race) -> None:
        mine = parts[name]
        cancel = mine.cancel
        assert cancel is not None
        try:
            for n in idx:
                if cancel.is_set():
                    self.drop(plan.steps[n], n, mine, cancel.red)
                    continue
                self.step(plan.steps[n], n, mine)
                if mine.red:
                    self._first_red(name, mine, parts, race)
        except BaseException as e:  # a check's fault: the other lanes are stopped, the owner raises it
            with race.lock:
                race.fails.append(Fail(name, e))
            self._cancel(parts, name, f"lane {name or 'default'} stopped the round")

    def _first_red(self, name: str, mine: Round, parts: dict[str, Round], race: Race) -> None:
        with race.lock:
            if race.first is None:
                race.first = name
        self._cancel(parts, name, mine.results[-1].id)

    @staticmethod
    def _cancel(parts: dict[str, Round], keep: str, red: str) -> None:
        """Cancel every lane but `keep`, saying which check went red (the first to say wins)."""
        for lane, part in parts.items():
            c = part.cancel
            if lane != keep and c is not None and not c.is_set():
                c.red = red
                c.set()

    @staticmethod
    def _fold(st: Round, parts: dict[str, Round], first: str) -> Round:
        by_step = {n: res for part in parts.values() for n, res in part.by_step.items()}
        for n in sorted(by_step):
            st.results.append(by_step[n])
        st.by_step.update(by_step)
        for part in parts.values():
            st.env.update(part.env)
            st.timings.extend(part.timings)
            st.changed = part.changed if part.changed is not None else st.changed
        if first:
            st.red = parts[first].red
        return st


def replace_round(st: Round, cancel: Cancel) -> Round:
    """A lane's own round: the numbers of `st`, nothing decided yet, the lane's flag."""
    return replace(st, results=[], by_step={}, red="", red_skipped=set(), env=dict(st.env), timings=[], cancel=cancel)
