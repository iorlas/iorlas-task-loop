"""Time spent waiting for a shared resource (a lock, a slot): recorded as its own segment, never counted in budget_min."""
import contextlib
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from tlkernel import askspecs
from tlkernel import log as rec
from tlkernel.checkmatchers import slot_wait_secs
from tlkernel.config import EngineConfig
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.lanesliveness import LIVENESS
from tlkernel.ports import Clock
from tlkernel.stagefacts import RunLogPort
from tlkernel.waitenums import WaitWhat
from tlpipeline import outcomes
from tlpipeline.adapter_ports import Deadline
from tlpipeline.blocked import Blocked
from tlpipeline.steps import Open
from tlpipeline.store_ports import WaitStores


class WaitsBudget(Protocol):
    def wait(self, secs: float) -> float: ...
    def over(self) -> list[str]: ...


class WaitsSteps(Protocol):
    """The step book, as a wait reads it: end the open step, and which one is open."""

    @property
    def cur(self) -> Open | None: ...
    def end(self) -> None: ...


class WaitsHost(Protocol):
    """What Waits reads of the engine: the log, the clock, the budget and the counters it books waits against."""

    @property
    def waited(self) -> float: ...  # seconds spent waiting for a shared resource, not counted in budget_min

    @property
    def bead(self) -> BeadId: ...
    @property
    def cfg(self) -> EngineConfig: ...
    @property
    def log(self) -> RunLogPort: ...
    @property
    def clock(self) -> Clock: ...
    @property
    def budget(self) -> WaitsBudget: ...
    @property
    def steps(self) -> WaitsSteps: ...
    @property
    def stats(self) -> dict[str, int]: ...
    @property
    def stores(self) -> WaitStores: ...
    @property
    def log_path(self) -> Path: ...

    def os_lock(self, path: Path | str, holder: str, waiting: Callable[[str], None] | None = ..., timeout: float | None = ...,
                check: Callable[[], None] | None = ...) -> AbstractContextManager[Path | str]: ...
    def halt_point(self, when: bool = ..., wait: float = ...) -> None: ...


class Waits:
    def __init__(self, host: WaitsHost, deadline: Deadline) -> None:
        self.host = host
        self.deadline = deadline
        self.earlier: tuple[int, int] | None = None  # (tokens, runs) of the bead's earlier runs

    def start(self, what: WaitWhat, holder: str = "", until: float | None = None, track: str = "", check: str = "") -> str:
        """A wait begins (before the sleep, so a wait still going shows): its id, which add closes. `track` and `check`: the
        waiting check of a resource wait."""
        wid: str = self.host.log.next_id("w")
        self.host.log.emit(rec.WaitStart(id=wid, what=what, holder=holder, until=until, track=track, check=check))
        return wid

    def add(self, secs: float, what: WaitWhat, wid: str | None = None, track: str = "", check: str = "") -> None:
        """`secs` spent waiting for a shared resource (not the budget's), the end of the wait `wid` (written now when not begun)."""
        secs = self.host.budget.wait(secs)
        if wid or secs > 0:
            wid = wid or self.start(what, track=track, check=check)
            if secs > 0:
                self.host.log.note(
                    "waited {} min for {}: not counted in budget_min".format(int(secs // 60), what.value.replace("_", " ")))
            self.host.log.emit(rec.WaitEnd(id=wid, wait_seconds=round(secs), in_budget=False, track=track, check=check))

    @contextlib.contextmanager
    def locked(self, what: str, path: Path | str, holder: str | None = None) -> Generator[Path | str]:
        """landlock.os_lock with a wait recorded as its own segment (tl-9h2): the open step ends before the wait starts (it was
        booked to the step before), and the wait's records name the lock, who held it and how long it took. The lock is a record
        of its own while held. tl-y35: the wait is a wait for a shared resource like any other: it is added to `waited`, so
        budget_min does not count it. Timed on the engine's clock."""
        who: list[str] = []
        t_req = [self.host.clock.now()]
        wid: list[str] = []

        def waiting(w: str) -> None:
            who.append(w)
            self.host.steps.end()
            t_req[0] = self.host.clock.now()  # the wait starts when the step before it has ended
            wid.append(self.start(WaitWhat(what), w))  # a wait still going (or cut off) shows up
            self.host.log.note("waiting for the {} (held by {})".format(what.replace("_", " "), w))
        acquired = False

        def waited() -> None:
            if who:
                secs = max(0.0, self.host.clock.now() - t_req[0])
                self.host.budget.wait(secs)
                self.host.log.emit(rec.WaitEnd(id=wid[0], wait_seconds=round(secs), in_budget=False))
                who.clear()

        try:
            with self.host.os_lock(
                path, holder or self.host.bead, waiting,
                timeout=self.deadline.remaining(LIVENESS.lock_wait_s), check=self.host.halt_point,
            ):
                acquired = True
                waited()
                held = self.host.clock.now()
                self.host.log.emit(rec.Lock(what=what.removesuffix("_lock"), holder=holder or self.host.bead))
                try:
                    yield path
                finally:
                    self.host.log.emit(rec.Unlock(what=what.removesuffix("_lock"), secs=round(self.host.clock.now() - held, 1)))
        except TimeoutError as err:
            if acquired:
                raise
            self.deadline.check()
            raise Blocked(f"paused: {what} wait deadline exceeded (held by {err}); retry later", kind=Kind.PAUSE_LANE) from None
        finally:
            waited()

    def note_slot_waits(self, text: str, wall: float) -> None:
        """A check's output says how long it queued for a Unity slot ("unity-slot: x got slot 0 after 686s"). The output
        is not trusted: all the waits in one run together are at most that run's wall time."""
        self.add(min(slot_wait_secs(text), wall), WaitWhat.CHECK_SLOT)

    def token_cap_check(self) -> None:
        """engine.bead_token_cap: the bead's tokens (in + out) over its earlier runs (traces.jsonl, read once) and this one so far."""
        cap = self.host.cfg.bead_token_cap
        if cap <= 0:
            return
        if self.earlier is None:
            rows = [i.rec for i in self.host.stores.traces.read_from(0).items if i.rec.bead == self.host.bead]
            self.earlier = (sum(r.stats.tokens_in + r.stats.tokens_out for r in rows), len(rows))
        now = self.host.stats["tokens_in"] + self.host.stats["tokens_out"]
        used = self.earlier[0] + now
        if used >= cap:
            runs = self.earlier[1] + (1 if now else 0)
            raise Blocked(f"bead used {askspecs.million(used)} tokens over {runs} run{'' if runs == 1 else 's'} "
                          f"(cap {askspecs.million(cap)}): raise engine.bead_token_cap or split the bead",
                          askspecs.token_cap(used, runs, cap), kind=Kind.ASK_BUDGET)

    def budget_check(self) -> None:
        self.token_cap_check()
        over = self.host.budget.over()
        if over:
            steps = outcomes.run_breakdown(self.host.log_path, self.host.steps.cur)
            went = ", ".join("{} {} min ({} round{})".format(b.step, b.minutes, b.rounds, "" if b.rounds == 1 else "s") for b in steps)
            waited = f" ({int(self.host.waited // 60)} min waiting for shared resources not counted)" if self.host.waited >= 60 else ""
            raise Blocked("over budget: {}{}{}".format(", ".join(over), (". Where it went: " + went) if went else "", waited),
                          askspecs.over_budget(over, steps, int(self.host.waited // 60)), kind=Kind.ASK_BUDGET)
