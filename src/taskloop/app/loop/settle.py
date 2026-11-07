"""Count a bead's verdict, cool it, set a broken slot aside, or wait for a resource to recover.
Only a configuration refusal ends the loop here; NETPAUSE keeps its own counters and probes."""
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from os import EX_CONFIG

from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure
from tlkernel.config import LoopConfig
from tlkernel.enums import Result
from tlkernel.ids import BeadId
from tlkernel.loop import LoopWait
from tlkernel.parks import ParkStore
from tlkernel.slots import SlotFail, SlotGitError

from taskloop.app.loop import verdict as vd
from taskloop.app.loop.env import LoopEnv, Probe
from taskloop.app.loop.files import LoopFiles
from taskloop.app.loop.net import NetState


@dataclass
class Counters:
    fails: list[str] = field(default_factory=list)  # runs in a row that gave no verdict
    ran: int = 0
    later: dict[str, float] = field(default_factory=dict)  # a paused or taken bead -> when to try it again
    warned: list[str] = field(default_factory=list)  # once-per-loop-run warnings (a missing install dir)
    slot_quick: dict[str, list[str]] = field(default_factory=dict)  # slot -> the beads that failed in an instant there, in a row
    slot_blocked: dict[str, str] = field(default_factory=dict)  # slot -> bead requiring recovery or different work
    net_first: list[str] = field(default_factory=list)  # beads the network paused: they go first when it is back
    net_down_t: float = 0.0
    wait: LoopWait | None = None


class Settle:
    def __init__(self, env: LoopEnv, files: LoopFiles, tune: Callable[[], LoopConfig], say: Callable[[str], None], c: Counters,
                 net: NetState, left: Callable[[str, str], None]) -> None:
        self.env, self.files, self.tune, self.say, self.c, self.net, self.left = env, files, tune, say, c, net, left
        self.probe: Probe | None = None

    def aside(self, name: str, bid: str, v: vd.Verdict) -> bool:
        """Stop retaking this bead until recovery or different eligible work."""
        t = self.tune()
        quick = self.c.slot_quick.setdefault(name, [])
        why = f"{len(quick)} runs failed within {t.quick_fail_min:g} min each ({', '.join(quick)}): last: {v.why[:160]}"
        self.c.slot_blocked[name] = bid
        self.env.slots.mark_aside(name)
        self.say(f"SLOT {name}: {bid} waits for a successful reset probe or a different eligible bead: {why}")
        self.env.event("slot_aside", bid, slot=name, why=why, held=False, repo=self.env.repo)
        self.c.fails = [f for f in self.c.fails if f not in quick]
        self.c.slot_quick[name] = []
        return True

    def candidates(self, name: str, cands: list[Bead]) -> list[Bead]:
        """The slot is claimed by this loop. Prefer different work, otherwise prove recovery."""
        for source, blocked in list(self.c.slot_blocked.items()):
            different = [b for b in cands if b.id != blocked]
            if different or self.recovered(source, name):
                self.c.slot_blocked.pop(source, None)
                cands = different or cands
            else:
                cands = []
        return cands

    def recovered(self, source: str, claimed: str) -> bool:
        """A loop cannot evade the bead's recovery condition by taking another slot."""
        return self.env.slots.aside_recovered(source, claimed)

    def count_slot(self, v: vd.Verdict, bid: str, name: str) -> bool:
        """True when the slot was set aside for this failure: the bead's turn is over, nothing else is counted."""
        quick = v.quick_slot_failure(self.tune().quick_fail_min)
        # The engine found another branch's unsaved work in this slot. That is already
        # evidence of a slot fault; a reset probe must not erase it (or touch that work).
        dirty_branch = (v.why.startswith("failed: worktree ")
                        and v.why.endswith(" has uncommitted work of another branch"))
        if quick and not v.pre_engine and not dirty_branch:
            try:
                self.env.slots.check_ready(name)
                quick = False
            except SlotFail as err:
                quick = err.code == "slot_broken"
            except (BdFailure, SlotGitError, OSError):
                quick = False
        previous = self.c.slot_quick.get(name, [])
        self.c.slot_quick[name] = ([*previous, bid] if previous and previous[-1] == bid else [bid]) if quick else []
        return len(self.c.slot_quick[name]) >= self.tune().slot_fails_to_set_aside and self.aside(name, bid, v)

    def network(self, v: vd.Verdict, bid: str) -> None:
        """tl-kyy: the machine is offline. It is no run, no failure and no pause of the bead's: no label is touched, no counter
        moves, and the bead is not rested. The loop probes and resumes the same bead."""
        t, env = self.tune(), self.env
        self.probe = self.probe or env.probe()
        if self.probe is None:
            self.c.later[bid] = env.now() + t.pause_retry
            self.say(f"{bid} paused for the network and no delegate is installed to probe it: the next bead first")
            return
        if self.net.mark_down(env.now()):
            self.c.net_down_t = env.now()
            self.say(f"NETWORK DOWN: {bid} paused; no bead is claimed until the probe passes (every {t.net_probe:g} s)")
            env.event("net_down", bid, who="loop", repo=env.repo, why=v.why[:200])
        if bid not in self.c.net_first:
            self.c.net_first.append(bid)

    def paused(self, v: vd.Verdict, bid: str, name: str, slots: bool) -> int | None:
        self.say(f"{bid} paused without a park ({v.why[:120]}): a fault, retrying")
        return self.failed(v.with_(kind="fault_unparked"), bid, name, slots)

    def failed(self, v: vd.Verdict, bid: str, name: str, slots: bool) -> int | None:
        c = self.c
        if not v.fault and not (slots and name and c.slot_quick.get(name)):
            c.fails.append(bid)
        return None

    def apply(self, v: vd.Verdict, bid: str, name: str, slots: bool) -> int | None:
        """None: the loop goes on."""
        t, c, env = self.tune(), self.c, self.env
        if v.kind == vd.PROFILE_AHEAD:
            self.say(v.why)
            self.left(vd.PROFILE_AHEAD, v.why)
            return EX_CONFIG
        if v.paused_for_network:
            self.network(v, bid)
            return None
        if slots and name and self.count_slot(v, bid, name):
            return None
        rec = ParkStore(env.cfgdir).get(BeadId(bid)) if bid else None
        if rec and rec.reason and rec.run == v.run:
            c.later.pop(bid, None)
            if rec.permanence == "transient":
                c.later[bid] = rec.retry_at
                self.say(f"{bid}: {rec.reason}; retry at {time.strftime('%H:%M', time.localtime(rec.retry_at))}")
            else:
                self.say(f"{bid}: {rec.reason}; parked for the owner")
            return None
        if v.pre_engine:  # the engine never started: no verdict on the run, so no failure toward the stop
            c.later[bid] = env.now() + t.pause_retry
            self.say(f"{bid} waiting for infrastructure before its engine starts: it will be retried")
            return None
        return self.counted(v, bid, name, slots)

    def counted(self, v: vd.Verdict, bid: str, name: str, slots: bool) -> int | None:
        c = self.c
        c.ran += 1
        if v.outcome is Result.LANDED:
            c.fails = []
        elif v.outcome is Result.FAILED:
            return self.failed(v, bid, name, slots)
        elif v.outcome is Result.PAUSED:
            return self.paused(v, bid, name, slots)
        return None
