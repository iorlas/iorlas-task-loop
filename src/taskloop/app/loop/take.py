"""From a free slot to a verdict: the area check, the claim, the slot's reset and the run, bead after bead until one is run."""
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from os import EX_CONFIG

from taskloop.app.asks import parks
from taskloop.app.loop import verdict as vd
from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.queue import QueueRule, has_areas
from taskloop.app.loop.run import BeadRun, Where
from taskloop.app.slots.env import attempt
from taskloop.app.slots.lease import Lease
from taskloop.app.slots.pool import SlotPool
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import ConfigError, EngineConfig, LoopConfig
from taskloop.contracts.enums import Result
from taskloop.contracts.parks import ParkStore
from taskloop.contracts.ports import BdFailure, BeadPatch
from taskloop.contracts.slots import SlotFail, SlotGitError
from taskloop.domain.lanes import pauses


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
        try:
            senv = self.env.slot_env()
            target = SlotPool(senv).named(slot)
            try:
                target.ready_for(bead)
            except SlotFail as e:
                if e.code != "slot_broken":
                    raise
                target.ready_for(bead)  # retry preservation/reset/setup before counting a slot fault
            return None
        except (BdFailure, SlotGitError, OSError) as e:
            attempt(self.env.store.unclaim, bead)
            return vd.pre_engine(str(e))
        except SlotFail as e:
            attempt(self.env.store.unclaim, bead)
            if e.code == "bead_pinned":  # a live run holds the bead's branch: not this loop's failure
                return vd.taken(e.why)
            if e.code == "busy":
                return vd.pre_engine(f"tl slot reset {slot} for {bead} found the slot busy (a live engine or a hold)")
            return vd.pre_engine(f"tl slot reset {slot} for {bead} did not give a clean tree: {e.why}", e.code,
                                 recovery_failed=e.code == "slot_broken")

    def claimed(self, b: Bead, at: Where, ecfg: EngineConfig, rule: QueueRule) -> vd.Verdict | None:
        """The area check, the claim and the mark that makes the area busy, as one. A verdict: the bead is not to be run now;
        None with an empty `why`: go on."""
        env = self.env
        with env.area_lock() if has_areas(ecfg) else contextlib.nullcontext():
            if has_areas(ecfg):
                rule.running = env.running()  # now, not as the queue was read: the slot wait since can be minutes (tl-na3)
            area, busy = rule.area_busy(b) if has_areas(ecfg) else ("", None)
            if busy:  # another run took the area since the queue was read
                self.say(f"{b.id}: {busy.why}; the next bead")
                return vd.Verdict(Result.SKIPPED)
            won, why = env.claim(b.id, at.wt, at.slot)
            if not won:
                return vd.taken(why)
            if area:
                env.loop_lock(at.wt, at.slot, at.slot_bead, b.id)
                if at.slot_bead:
                    attempt(env.store.update, at.slot_bead, BeadPatch(set_metadata={"held_bead": b.id}))
        return None

    def _park_profile_ahead(self, b: Bead, v: vd.Verdict) -> None:
        if v.kind == vd.PROFILE_AHEAD:
            env = self.env
            store = ParkStore(env.cfgdir)
            run = v.run or f"profile-ahead-{env.pid}-{env.now()}"
            store.put(pauses.after_pause(store.get(b.id), b, run, env.now(), v.kind, lambda: 0.5))

    def attempt_all(self, cands: list[Bead], at: Where, slots: bool, ecfg: EngineConfig, rule: QueueRule,
                    lease: Lease) -> Taken:
        env, bid = self.env, ""
        v: vd.Verdict | None = None
        for b in cands:
            bid = b.id
            if parks.gate(env.cfgdir, b, now=env.now()) is not None:
                continue
            try:
                held = self.claimed(b, at, ecfg, rule)
            except (BdFailure, SlotGitError, OSError) as e:
                attempt(env.store.unclaim, b.id)
                held = vd.pre_engine(str(e))
            if held is not None:
                if held.outcome is Result.SKIPPED:
                    continue
                self.record(bid, at.slot, held)
                self.later[bid] = env.now() + self.tune().pause_retry
                if held.pre_engine:
                    return Taken(held, bid)
                continue
            lease.add(bid)
            try:
                v = (self.prepare(at.slot, b.id) if slots else None) or self.run.run(b, at)
            except (ConfigError, SystemExit) as err:
                if isinstance(err, SystemExit) and err.code != EX_CONFIG:
                    raise
                attempt(env.store.update, b.id, BeadPatch(status="open", assignee=""))
                v = vd.profile_ahead(env.version)
            except (BdFailure, SlotGitError, OSError) as e:
                attempt(env.store.unclaim, b.id)
                v = vd.pre_engine(str(e))
            self._park_profile_ahead(b, v)
            self.record(b.id, at.slot, v)
            if v.outcome is not Result.TAKEN:
                break
            self.later[bid] = env.now() + self.tune().pause_retry
            lease.drop(bid)
            v = None
            if at.slot_bead:  # the next candidate's area check must not see this one as running here
                attempt(env.store.update, at.slot_bead, BeadPatch(unset_metadata=["held_bead"]))
            env.loop_lock(at.wt, at.slot, at.slot_bead, "")
        return Taken(v, bid)
