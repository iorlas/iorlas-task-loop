"""Time spent waiting for a shared resource (a lock, a slot): recorded as its own segment, never counted in budget_min."""
import contextlib
from collections.abc import Iterator
from typing import Any

from taskloop.app.run import outcomes
from taskloop.app.run.blocked import Blocked
from taskloop.contracts import log as rec
from taskloop.contracts.enums import WaitWhat
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.checks.matchers import slot_wait_secs


class Waits:
    def __init__(self, host: Any) -> None:
        self.e = host
        self.earlier: tuple[int, int] | None = None  # (tokens, runs) of the bead's earlier runs

    def start(self, what: Any, holder: str = "", until: Any = None) -> str:
        """A wait begins (before the sleep, so a wait still going shows): its id, which add closes."""
        wid: str = self.e.log.next_id("w")
        self.e.log.emit(rec.WaitStart(id=wid, what=what, holder=holder, until=until))
        return wid

    def add(self, secs: float, what: Any, wid: str | None = None) -> None:
        """`secs` spent waiting for a shared resource (not the budget's), the end of the wait `wid` (written now when not begun)."""
        e = self.e
        secs = e.budget.wait(secs)
        if wid or secs > 0:
            wid = wid or self.start(what)
            if secs > 0:
                e.log.note("waited {} min for {}: not counted in budget_min".format(int(secs // 60), what.value.replace("_", " ")))
            e.log.emit(rec.WaitEnd(id=wid, secs=round(secs), in_budget=False))

    @contextlib.contextmanager
    def locked(self, what: str, path: Any, holder: Any = None) -> Iterator[Any]:
        """landlock.os_lock with a wait recorded as its own segment (tl-9h2): the open step ends before the wait starts (it was
        booked to the step before), and the wait's records name the lock, who held it and how long it took. The lock is a record
        of its own while held. tl-y35: the wait is a wait for a shared resource like any other: it is added to `waited`, so
        budget_min does not count it. Timed on the engine's clock."""
        e = self.e
        who: list[str] = []
        t_req = [e.clock.now()]
        wid: list[str] = []

        def waiting(w: str) -> None:
            who.append(w)
            e.steps.end()
            t_req[0] = e.clock.now()  # the wait starts when the step before it has ended
            wid.append(self.start(WaitWhat(what), w))  # a wait still going (or cut off) shows up
            e.log.note("waiting for the {} (held by {})".format(what.replace("_", " "), w))
        with e.os_lock(path, holder or e.bead, waiting, check=e.halt_point):
            if who:
                secs = max(0.0, e.clock.now() - t_req[0])
                e.waited += secs
                e.log.emit(rec.WaitEnd(id=wid[0], secs=round(secs), in_budget=False))
            held = e.clock.now()
            e.log.emit(rec.Lock(what=what.removesuffix("_lock"), holder=holder or e.bead))
            try:
                yield path
            finally:
                e.log.emit(rec.Unlock(what=what.removesuffix("_lock"), secs=round(e.clock.now() - held, 1)))

    def note_slot_waits(self, text: str, wall: float) -> None:
        """A check's output says how long it queued for a Unity slot ("unity-slot: x got slot 0 after 686s"). The output
        is not trusted: all the waits in one run together are at most that run's wall time."""
        self.add(min(slot_wait_secs(text), wall), WaitWhat.UNITY_SLOT)

    def token_cap_check(self) -> None:
        """engine.bead_token_cap: the bead's tokens (in + out) over its earlier runs (traces.jsonl, read once) and this one so far."""
        e = self.e
        cap = int(e.cfg.bead_token_cap)
        if cap <= 0:
            return
        if self.earlier is None:
            rows = [i.rec for i in e.stores.traces.read_from(0).items if i.rec.bead == e.bead]
            self.earlier = (sum(r.stats.tokens_in + r.stats.tokens_out for r in rows), len(rows))
        now = e.stats["tokens_in"] + e.stats["tokens_out"]
        used = self.earlier[0] + now
        if used >= cap:
            runs = self.earlier[1] + (1 if now else 0)
            raise Blocked(f"bead used {askspecs.million(used)} tokens over {runs} run{'' if runs == 1 else 's'} "
                          f"(cap {askspecs.million(cap)}): raise engine.bead_token_cap or split the bead",
                          askspecs.token_cap(used, runs, cap), kind=oc.Kind.ASK_BUDGET)

    def budget_check(self) -> None:
        e = self.e
        self.token_cap_check()
        over = e.budget.over()
        if over:
            steps = outcomes.run_breakdown(e.log_path, e.steps.cur)
            went = ", ".join("{} {} min ({} round{})".format(b.step, b.minutes, b.rounds, "" if b.rounds == 1 else "s") for b in steps)
            waited = f" ({int(e.waited // 60)} min waiting for shared resources not counted)" if e.waited >= 60 else ""
            raise Blocked("over budget: {}{}{}".format(", ".join(over), (". Where it went: " + went) if went else "", waited),
                          askspecs.over_budget(over, steps, e.waited // 60), kind=oc.Kind.ASK_BUDGET)
