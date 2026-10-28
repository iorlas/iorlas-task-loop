"""From a free slot to a verdict: the area check, the claim, the slot's reset and the run, bead after bead until one is run."""
import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from taskloop.app.loop import verdict as vd
from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.queue import QueueRule, has_areas
from taskloop.app.loop.run import BeadRun, Where
from taskloop.app.slots.env import attempt
from taskloop.app.slots.lease import Lease
from taskloop.app.slots.pool import SlotPool
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import EngineConfig, LoopConfig
from taskloop.contracts.ports import BeadPatch
from taskloop.contracts.slots import SlotFail


@dataclass
class Taken:
    """The outcome of a try at the candidates: the verdict of the bead that ran, None when every one was held elsewhere."""

    verdict: vd.Verdict | None
    bead: str


class Taker:
    def __init__(self, env: LoopEnv, run: BeadRun, tune: Callable[[], LoopConfig], say: Callable[[str], None],
                 record: Callable[[str, str, vd.Verdict], None], later: dict[str, float]) -> None:
        self.env, self.run, self.tune, self.say, self.record, self.later = env, run, tune, say, record, later

    def prepare(self, slot: str, bead: str) -> vd.Verdict | None:
        """A slot gets a clean tree on the bead's branch (leftover work committed, never wiped). None when it did."""
        senv = self.env.slot_env()
        try:
            SlotPool(senv).named(slot).ready_for(bead)
            return None
        except SlotFail as e:
            if e.code == "slot_broken":
                senv.warn("tl: " + e.why)
            else:
                senv.say(("BUSY: " if e.code == "busy" else "TAKEN: ") + e.why)
            attempt(self.env.store.unclaim, bead)
            if e.code == "bead_pinned":  # a live run holds the bead's branch: not this loop's failure
                return vd.taken(e.why)
            if e.code == "busy":
                return vd.pre_engine(f"tl slot reset {slot} for {bead} found the slot busy (a live engine or a hold)")
            return vd.pre_engine(f"tl slot reset {slot} for {bead} did not give a clean tree: {e.why}", "slot_broken")

    def claimed(self, b: Bead, at: Where, ecfg: EngineConfig, rule: QueueRule) -> vd.Verdict | None:
        """The area check, the claim and the mark that makes the area busy, as one. A verdict: the bead is not to be run now;
        None with an empty `why`: go on."""
        env = self.env
        with env.area_lock() if has_areas(ecfg) else contextlib.nullcontext():
            area, busy = rule.area_busy(b) if has_areas(ecfg) else ("", None)
            if busy:  # another run took the area since the queue was read
                self.say(f"{b.id}: {busy.why}; the next bead")
                return vd.Verdict("skipped")
            won, why = env.claim(b.id, at.wt, at.slot)
            if not won:
                return vd.taken(why)
            if area:
                env.loop_lock(at.wt, at.slot, at.slot_bead, b.id)
                if at.slot_bead:
                    attempt(env.store.update, at.slot_bead, BeadPatch(set_metadata={"held_bead": b.id}))
        return None

    def attempt_all(self, cands: list[Bead], at: Where, slots: bool, ecfg: EngineConfig, rule: QueueRule,
                    lease: Lease) -> Taken:
        env, bid = self.env, ""
        v: vd.Verdict | None = None
        for b in cands:
            bid = b.id
            held = self.claimed(b, at, ecfg, rule)
            if held is not None:
                if held.outcome == "skipped":
                    continue
                self.record(bid, at.slot, held)
                self.later[bid] = env.now() + self.tune().pause_retry
                continue
            lease.add(bid)
            v = (self.prepare(at.slot, b.id) if slots else None) or self.run.run(b, at)
            self.record(b.id, at.slot, v)
            if v.outcome != "taken":
                break
            self.later[bid] = env.now() + self.tune().pause_retry
            lease.drop(bid)
            v = None
            if at.slot_bead:  # the next candidate's area check must not see this one as running here
                attempt(env.store.update, at.slot_bead, BeadPatch(unset_metadata=["held_bead"]))
            env.loop_lock(at.wt, at.slot, at.slot_bead, "")
        return Taken(v, bid)
