"""Tracks: the steps of a round that name different tracks run at the same time, each track's steps in order. The first red of any track
cancels the others: a track's running check is stopped through the Spawner (its own process tree, with the engine's usual stop and
grace), its queue for a resource lease ends, and its steps not yet begun are recorded as cancelled, never as a verdict. A stop of the
whole run (the halt) is passed to every track the same way. Nothing of a cancelled track is remembered as green."""
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from tlgate.domain.plan import CheckPlan, Step
from tlgate.round import Cancel, Round

STOP_JOIN_S = 60.0
POLL_S = 0.05  # how often the owner looks at the run's halt while the tracks run


class TrackStuck(RuntimeError):
    """Tracks that did not end within the run stop deadline."""


class TrackHost(Protocol):
    def halt_point(self, when: bool = ..., wait: float = ...) -> None: ...


@dataclass
class Fail:
    """A track that ended in an exception (a fault of the check, the run's stop): re-raised by the owner once every track has ended."""

    track: str
    error: BaseException


@dataclass
class Race:
    """Which track went red first, and what stopped by it."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    first: str | None = None
    fails: list[Fail] = field(default_factory=list)


class Tracks:
    def __init__(self, host: TrackHost, step: Callable[[Step, int, Round], None],
                 drop: Callable[[Step, int, Round, str], None]) -> None:
        self.host, self.step, self.drop = host, step, drop

    def run(self, plan: CheckPlan, tracks: dict[str, list[int]], st: Round) -> Round:
        """Run every track at once and fold what they decided into `st`, the results in plan order."""
        parts = {name: replace_round(st, Cancel()) for name in tracks}
        race = Race()
        threads = [threading.Thread(target=self._track, args=(name, plan, idx, parts, race), name=f"track-{name or 'default'}", daemon=True)
                   for name, idx in tracks.items()]
        for t in threads:
            t.start()
        try:
            pending = list(threads)
            while pending:
                pending[0].join(POLL_S)
                pending = [t for t in pending if t.is_alive()]
                self.host.halt_point()  # a stop of the run raises here: the tracks are cancelled below
        except BaseException as err:
            self._cancel(parts, "", "the run was stopped")
            deadline = time.monotonic() + STOP_JOIN_S
            for t in threads:
                t.join(max(0.0, deadline - time.monotonic()))
            stuck = [t.name for t in threads if t.is_alive()]
            if stuck:
                message = f"Tracks still running after {STOP_JOIN_S} seconds: {', '.join(stuck)}"
                print(message, file=sys.stderr, flush=True)
                _dump_threads()
                raise TrackStuck(message) from err
            raise
        if race.fails:
            raise race.fails[0].error
        return self._fold(st, parts, race.first or "")

    def _track(self, name: str, plan: CheckPlan, idx: list[int], parts: dict[str, Round], race: Race) -> None:
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
        except BaseException as e:  # a check's fault: the other tracks are stopped, the owner raises it
            with race.lock:
                race.fails.append(Fail(name, e))
            self._cancel(parts, name, f"track {name or 'default'} stopped the round")

    def _first_red(self, name: str, mine: Round, parts: dict[str, Round], race: Race) -> None:
        with race.lock:
            if race.first is None:
                race.first = name
        self._cancel(parts, name, mine.results[-1].id)

    @staticmethod
    def _cancel(parts: dict[str, Round], keep: str, red: str) -> None:
        """Cancel every track but `keep`, saying which check went red (the first to say wins)."""
        for track, part in parts.items():
            c = part.cancel
            if track != keep and c is not None and not c.is_set():
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
    """A track's own round: the numbers of `st`, nothing decided yet, the track's flag."""
    return replace(st, results=[], by_step={}, red="", red_skipped=set(), env=dict(st.env), timings=[], cancel=cancel)


def _dump_threads() -> None:
    """Report live thread stacks without expanding the stages' import closures."""
    frames = sys._current_frames()
    for thread in threading.enumerate():
        print(f"Thread {thread.name} ({thread.ident}):", file=sys.stderr)
        frame = frames.get(thread.ident) if thread.ident is not None else None
        while frame is not None:
            code = frame.f_code
            print(f'  File "{code.co_filename}", line {frame.f_lineno}, in {code.co_name}', file=sys.stderr)
            frame = frame.f_back
    sys.stderr.flush()
