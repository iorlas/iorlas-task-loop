"""What the loop does with a bead's verdict: count it, rest the bead, set a broken slot aside, hold the loop for the network
or stop it. Returns the loop's exit code when the verdict ends it."""
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

from taskloop.app.loop import verdict as vd
from taskloop.app.loop.env import LoopEnv, Probe
from taskloop.app.loop.files import LoopFiles
from taskloop.app.loop.gate import GateRole
from taskloop.app.loop.net import NetState
from taskloop.app.slots import verbs
from taskloop.contracts.config import LoopConfig


@dataclass
class Counters:
    fails: list[str] = field(default_factory=list)  # runs in a row that gave no verdict
    ran: int = 0
    later: dict[str, float] = field(default_factory=dict)  # a paused or taken bead -> when to try it again
    pauses: dict[str, int] = field(default_factory=dict)
    warned: list[str] = field(default_factory=list)  # installs not moved to
    slot_quick: dict[str, list[str]] = field(default_factory=dict)  # slot -> the beads that failed in an instant there, in a row
    net_first: list[str] = field(default_factory=list)  # beads the network paused: they go first when it is back
    net_down_t: float = 0.0


class Settle:
    def __init__(self, env: LoopEnv, files: LoopFiles, tune: Callable[[], LoopConfig], say: Callable[[str], None], c: Counters,
                 gate: GateRole, net: NetState, left: Callable[[str, str], None]) -> None:
        self.env, self.files, self.tune, self.say, self.c, self.gate, self.net, self.left = env, files, tune, say, c, gate, net, left
        self.probe: Probe | None = None

    def aside(self, name: str, bid: str, v: vd.Verdict) -> bool:
        """tl-g6a: a broken slot must not eat the queue: the failures are the slot's, not the beads' or the loop's. True when
        the slot is set aside (the failures before it no longer count toward the stop)."""
        t = self.tune()
        quick = self.c.slot_quick.setdefault(name, [])
        why = f"{len(quick)} runs failed within {t.quick_fail_min:g} min each ({', '.join(quick)}): last: {v.why[:160]}"
        ask = SimpleNamespace(name=name, why="set aside by tl loop: " + why, for_min=t.slot_aside_min)
        held = verbs.hold(self.env.slot_env(), ask) == 0
        hours = int(t.slot_aside_min // 60)
        self.say(f"SLOT {name} " + (f"SET ASIDE for {hours} h" if held else "could not be set aside (another loop has it)") + f": {why}")
        self.env.event("slot-aside", bid, slot=name, why=why, held=held, repo=self.env.repo)
        if held:
            self.c.fails = [f for f in self.c.fails if f not in quick]
            self.c.slot_quick[name] = []
        else:
            self.c.slot_quick[name] = quick[-1:]  # still failing: asked again after the next one
        return held

    def count_slot(self, v: vd.Verdict, bid: str, name: str) -> bool:
        """True when the slot was set aside for this failure: the bead's turn is over, nothing else is counted."""
        quick = v.quick_slot_failure(self.tune().quick_fail_min)
        self.c.slot_quick[name] = ([*self.c.slot_quick.get(name, []), bid]) if quick else []
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

    def paused(self, v: vd.Verdict, bid: str) -> None:
        t, c, env = self.tune(), self.c, self.env
        c.pauses[bid] = c.pauses.get(bid, 0) + 1
        if c.pauses[bid] >= t.pauses_to_rest:
            c.pauses[bid] = 0
            c.later[bid] = env.now() + t.rest
            self.say(f"{bid} paused {t.pauses_to_rest} times: it rests an hour, the next bead first")
        elif v.role and env.has_delegate():
            self.gate.hold(bid, v.role)  # the lane's own time is a hint: the bead wakes when delegate says the role is usable
            hint = f" (a time hint: {time.strftime('%H:%M:%S', time.localtime(v.retry_after))})" if v.retry_after else ""
            self.say(f"{bid} paused for the {v.role} role{hint}: it wakes when delegate says the role is usable, the next bead first")
        else:
            c.later[bid] = env.now() + t.pause_retry
            self.say(f"{bid} paused ({v.why[:120]}): the next bead first")

    def failed(self, v: vd.Verdict, bid: str, name: str, slots: bool) -> int | None:
        t, c, env = self.tune(), self.c, self.env
        if v.fault:  # a fault of the machine or the engine: the bead is open, labelled, cooled; the storm is the stop
            self.files.rest_bead(bid, env.now() + t.fault_cooldown)
            c.later[bid] = env.now() + t.fault_cooldown
        elif not (slots and name and c.slot_quick.get(name)):  # no verdict at all (run-task died); an instant slot failure is the slot's
            c.fails.append(bid)
        if len(c.fails) >= t.fails_to_stop:
            print(f"STOPPED: {len(c.fails)} failures in a row ({', '.join(c.fails)}); "
                  "look at their logs (tl loop status) before starting again")
            self.left("storm", f"{len(c.fails)} runs gave no outcome")
            return 2
        return None

    def apply(self, v: vd.Verdict, bid: str, name: str, slots: bool) -> int | None:
        """None: the loop goes on."""
        t, c, env = self.tune(), self.c, self.env
        if slots and name and self.count_slot(v, bid, name):
            return None
        if v.pre_engine:  # the engine never started: no verdict on the run, so no failure toward the stop
            self.files.rest_bead(bid, env.now() + t.rest)
            c.later[bid] = env.now() + t.rest
            self.say(f"{bid} failed before its engine started: it rests an hour for every loop on the repo, the next bead first")
            return None
        if v.paused_for_network:
            self.network(v, bid)
            return None
        c.ran += 1
        if v.storm:  # this run's close tripped the storm detector (the engine wrote the record and the banner)
            print(v.storm)
            self.left("storm", v.storm[:200])
            return 2
        if v.outcome == "landed":
            c.fails = []
        elif v.outcome == "failed":
            return self.failed(v, bid, name, slots)
        elif v.outcome == "paused":
            self.paused(v, bid)
        return None
