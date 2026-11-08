"""From a free slot to a verdict: the area check, the claim, the slot's reset and the run, bead after bead until one is run."""
from collections.abc import Callable
from dataclasses import dataclass
from os import EX_CONFIG

from tlareas import admission
from tlareas.host import AreasHost
from tlkernel.bdsafe import attempt
from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, BeadPatch
from tlkernel.config import ConfigError, EngineConfig, LoopConfig
from tlkernel.enums import Result
from tlkernel.ids import BeadId
from tlkernel.slots import SlotFail, SlotGitError

from taskloop.app.loop import verdict as vd
from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.ports import LeaseHandle
from taskloop.app.loop.queue import QueueRule
from taskloop.app.loop.run import BeadRun, Where


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
            try:
                self.env.slots.ready_for(slot, bead)
            except SlotFail as e:
                if e.code != "slot_broken":
                    raise
                self.env.slots.ready_for(slot, bead)  # retry preservation/reset/setup before counting a slot fault
            return None
        except (BdFailure, SlotGitError, OSError) as e:
            attempt(self.env.store.unclaim, BeadId(bead))
            return vd.pre_engine(str(e))
        except SlotFail as e:
            attempt(self.env.store.unclaim, BeadId(bead))
            if e.code == "bead_pinned":  # a live run holds the bead's branch: not this loop's failure
                return vd.taken(e.why)
            if e.code == "busy":
                return vd.pre_engine(f"tl slot reset {slot} for {bead} found the slot busy (a live engine or a hold)")
            if e.setup and self.env.slots.sets_up_at_base(slot):  # the slot is fine and clean at the base: the bead's tree breaks the setup
                return vd.setup_own_tree(e.why, f"setup-{self.env.pid}-{self.env.now()}")
            return vd.pre_engine(f"tl slot reset {slot} for {bead} did not give a clean tree: {e.why}", e.code,
                                 recovery_failed=e.code == "slot_broken")

    def claimed(self, b: Bead, at: Where, ecfg: EngineConfig, rule: QueueRule) -> vd.Verdict | None:
        """The area check, the claim and the mark that makes the area busy, as one. A verdict: the bead is not to be run now;
        None with an empty `why`: go on."""
        env = self.env
        def publish() -> None:
            env.loop_lock(at.wt, at.slot, at.slot_bead, b.id)
            if at.slot_bead:
                attempt(env.store.update, at.slot_bead, BeadPatch(set_metadata={"held_bead": b.id}))
        host = AreasHost(env.store, env.running, env.area_lock, self.say, ecfg.areas, ecfg.area_label_prefix)
        admitted = admission.loop(host, b, rule, lambda: env.claim(b.id, at.wt, at.slot), publish)
        if admitted.kind == "busy":
            self.say(f"{b.id}: {admitted.why}; the next bead")
            return vd.Verdict(Result.SKIPPED)
        if admitted.kind == "not_won":
            return vd.taken(admitted.why)
        return None

    def _park_profile_ahead(self, b: Bead, v: vd.Verdict) -> None:
        if v.kind in (vd.PROFILE_AHEAD, vd.SETUP_OWN_TREE):
            env = self.env
            run = v.run or f"profile-ahead-{env.pid}-{env.now()}"
            env.asks.profile_ahead(b, run, v.kind)

    def _held(self, bid: str, at: Where, held: vd.Verdict) -> Taken | None:
        """A bead that is not to be run now: recorded and cooled (a network pause is neither), and a pre-engine failure ends the pass."""
        if held.outcome is Result.SKIPPED:
            return None
        self.record(bid, at.slot, held)
        if not held.paused_for_network:
            self.later[bid] = self.env.now() + self.tune().pause_retry
        return Taken(held, bid) if held.pre_engine else None

    def attempt_all(self, cands: list[Bead], at: Where, slots: bool, ecfg: EngineConfig, rule: QueueRule,
                    lease: LeaseHandle) -> Taken:
        env, bid = self.env, ""
        v: vd.Verdict | None = None
        for b in cands:
            bid = b.id
            if env.asks.held(b):
                continue
            try:
                held = self.claimed(b, at, ecfg, rule)
            except (BdFailure, SlotGitError, OSError) as e:
                attempt(env.store.unclaim, b.id)
                held = vd.pre_engine(str(e))
            if held is not None:
                taken = self._held(bid, at, held)
                if taken is not None:
                    return taken
                continue
            lease.add(bid)
            try:
                v = (self.prepare(at.slot, b.id) if slots else None) or self.run.run(b, at)
            except (ConfigError, SystemExit) as err:
                if isinstance(err, SystemExit) and err.code != EX_CONFIG:
                    raise
                attempt(env.store.update, b.id, BeadPatch(status="open", assignee=""))
                v = vd.profile_ahead(env.version, err)
            except (BdFailure, SlotGitError, OSError) as e:
                attempt(env.store.unclaim, b.id)
                v = vd.pre_engine(str(e))
            if v.outcome is Result.TAKEN and not v.run:
                attempt(env.store.unclaim, b.id)
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
