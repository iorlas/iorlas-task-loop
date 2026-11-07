"""What every part of a run asks of the run itself: the stop flag and its safe points, the one poster of comments, the clock, the
Blocked a step raises, the host move."""
import threading
import time
from functools import cached_property
from pathlib import Path

from taskloop.adapters import beadtools
from taskloop.adapters import halt as halting
from taskloop.app.run.blocked import Blocked, FixFailed, blocked_for
from taskloop.app.run.console import say
from taskloop.app.run.fields import RunFields
from taskloop.app.track import trail
from taskloop.contracts import fence
from taskloop.contracts.kinds import Kind
from taskloop.contracts.log import Assumed, Said
from taskloop.domain.asks.spec import AskSpec
from taskloop.domain.checks import affinity
from taskloop.domain.matchers import redact


class Plumbing(RunFields):
    Blocked = Blocked  # the stop a step raises: components catch it through the host
    FixFailed = FixFailed
    stop_deferred = staticmethod(halting.stop_deferred)

    # the budget's numbers, read and set as the engine's own (waited: seconds spent waiting for a shared resource, not budget_min's)
    labels, cost = (property(lambda obj, k=k: getattr(obj.budget, k), lambda obj, v, k=k: setattr(obj.budget, k, v))
                    for k in ("labels", "spent"))

    @property
    def t0(self) -> float:
        return self.budget.t0

    @property
    def waited(self) -> float:
        return self.budget.waited

    @cached_property
    def halt(self) -> threading.Event:
        # The stop flag of the run: set from any thread (the SIGTERM handler does), sh() ends the command's tree, a worker call is
        # stopped and a wait ends; the run then stops at its next safe point (halt_point), never from inside a signal handler.
        return halting.RUN_HALT["ev"] or threading.Event()

    def halt_point(self, when: bool = True, wait: float = 0) -> None:  # a safe point (and a wait of `wait` s that a stop ends)
        if when and halting.nap(self.halt, wait):
            raise Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)

    def blocked_for(self, why: str, kind: str, stop: object = None, spec: AskSpec | None = None, fix: bool = False) -> Blocked:
        return blocked_for(why, kind, stop, spec, fix)

    def move_host(self, needs: list[str], why: str) -> Blocked:
        """The stop of a bead that needs a resource this host lacks: the needs labels are written under the claim's fence (only add,
        never remove), then the run ends PAUSE_MOVED and the close releases the bead for a host that has them."""
        lost = [n for n in needs if not beadtools.attempt(self.store.add_label, self.bead, affinity.label(n), fence.guard(self.claim))]
        if lost:
            return self.blocked_for(f"failed: could not label {self.bead} needs:{', '.join(lost)} ({why})", "FAULT_ENGINE")
        return self.blocked_for(why, "PAUSE_MOVED")

    def warn(self, text: str) -> None:
        """Something a watching coordinator should look at: printed with a warning sign, kept in the log, shown on the dashboard."""
        self.log.warn(text)

    def detail(self, lines: list[str]) -> None:
        """Verbose mode (the default): the facts behind a step, indented under it."""
        if self.verbose:
            for ln in lines:
                if ln:
                    say(f"           {ln[:400]}")

    def comment(self, text: str) -> None:
        """The one poster of the engine's comments on the bead: each is also a Said record, tied to the open step (or the last)."""
        if not self.dry:
            text = redact(text)  # Dolt keeps what a bead is told: no credential from a worker's or a check's output goes in
            self.log.emit(Said(step=self.step_id(), who="engine", text=text))
            beadtools.attempt(self.store.add_comment, self.bead, text)

    def assumed(self, text: str) -> None:
        """What the planner planned around instead of asking: an Assumed record, tied to the open step."""
        self.log.emit(Assumed(step=self.step_id(), text=text))

    def step_id(self) -> str:
        """The open step's id; between steps (the close-out after the close step), the last one's."""
        last = self.steps.cur or self.steps.last
        return last.id if last else ""

    @staticmethod
    def now() -> float:
        return time.time()  # looked up at each call: a test sets the wall clock

    def on_step(self, text: str) -> None:
        step = "close" if self.steps.cur and self.steps.cur.step == "close" else ""
        trail.event(self.who, "stage", self.bead, text=text, run_id=self.run_id, step=step)

    def call_dir(self) -> Path:
        return self.home.root / "checkpoints"
