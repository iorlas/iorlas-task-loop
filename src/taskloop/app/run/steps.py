"""Steps: the cursor over a run's steps. One step is open at a time; opening the next closes it. Every move writes its record."""

from collections.abc import Callable
from typing import Any

from taskloop.contracts.log import StepEnd, StepStart, Transition
from taskloop.stores.runlog import RunLog

META = ("stage", "stages", "round", "write", "fix")  # the counters a StepStart carries


class Open:
    """The step that is open (or was the last): its number, name, start, and what it came to."""

    def __init__(self, n: int, step: str, t: float) -> None:
        self.n, self.step, self.t, self.outcome, self.detail = n, step, t, "", ""

    @property
    def id(self) -> str:
        return "n%d" % self.n


class Steps:
    def __init__(
        self,
        log: RunLog,
        clock: Callable[[], float],
        guard: Callable[[str], None] | None = None,
        on_begin: Callable[[str], None] | None = None,
    ) -> None:
        self.log, self.clock, self.guard, self.on_begin = log, clock, guard, on_begin
        self.n = 0  # steps begun in this run (kept across a move to a newer install)
        self.cur: Open | None = None
        self.last: Open | None = None
        self.moved_from: int | None = None
        self.moved_to: str | None = None

    @property
    def id(self) -> str:
        """The id of the open step ('' when none is open)."""
        return self.cur.id if self.cur else ""

    def begin(self, step: str, text: str, **meta: Any) -> int:
        """A step begins (the open one ends first), after `guard` has looked at the tree."""
        if self.guard and step != "close":
            self.guard(step)
        self.end()
        self.n += 1
        self.cur = self.last = Open(self.n, step, self.clock())
        self.log.emit(StepStart(id=self.cur.id, step=step, text=text, **{k: meta[k] for k in META if meta.get(k) is not None}))
        if self.on_begin:
            self.on_begin(text)
        return self.n

    def outcome(self, outcome: str, detail: str = "") -> None:
        """What the open step came to, for its end record."""
        if self.cur:
            self.cur.outcome, self.cur.detail = outcome, detail[:300]

    def end(self, outcome: str = "") -> None:
        c, self.cur = self.cur, None
        if c:
            self.log.emit(
                StepEnd(id=c.id, step=c.step, outcome=c.outcome or outcome or "done", detail=c.detail, secs=round(self.clock() - c.t))
            )

    def move(self, to: str, cause: str, detail: str = "") -> None:
        """A decision point: from the open (or last) step to the next one, with the cause and what it was."""
        frm = self.cur or self.last
        self.moved_from, self.moved_to = (frm.n if frm else 0), to
        self.log.emit(Transition(from_id=frm.id if frm else "", to=to, cause=cause, detail=(detail or "")[:300]))
