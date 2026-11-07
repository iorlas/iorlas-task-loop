"""The adapters of the loop's ports (ports.py) over the real stages: slots and asks. This is where the loop meets them; the composition root
(launch/loop.py) builds these into the LoopEnv."""
from collections.abc import Callable

from taskloop.app.asks import deferral, parks
from taskloop.app.loop.ports import LeaseHandle
from taskloop.app.slots import aside, owned, watchdog
from taskloop.app.slots import line as slots_line
from taskloop.app.slots.env import SlotEnv
from taskloop.app.slots.lease import Lease
from taskloop.app.slots.pool import SlotPool
from taskloop.app.slots.reset import setup
from taskloop.contracts.bead import Bead
from taskloop.contracts.beadsport import BdFailure, Beads
from taskloop.contracts.ids import BeadId
from taskloop.contracts.loop import Skip
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.slots import SlotFail, SlotGitError


class EngineSlots:
    def __init__(self, slot_env: Callable[[], SlotEnv]) -> None:
        self.slot_env = slot_env
        self.watch = watchdog.Watch()  # the slot liveness look (tl-bxk.10.33.12)

    def ready_for(self, slot: str, bead: str) -> None:
        SlotPool(self.slot_env()).named(slot).ready_for(bead)

    def sets_up_at_base(self, slot: str) -> bool:
        try:
            target = SlotPool(self.slot_env()).named(slot)
            target.ready_for("")
            setup(target, force=True)
        except (SlotFail, SlotGitError, BdFailure, OSError):
            return False
        return True

    def mark_aside(self, name: str) -> None:
        aside.mark(SlotPool(self.slot_env()).named(name))

    def aside_recovered(self, source: str, claimed: str) -> bool:
        pool = SlotPool(self.slot_env())
        if source == claimed:
            return aside.check(pool.slot(source))
        with pool.env.take_lock():
            return aside.probe(pool.slot(source), required=True)

    def check_ready(self, name: str) -> None:
        SlotPool(self.slot_env()).named(name).check_ready()

    def tick(self, *, ready_since: float | None, idle_lanes: int) -> None:
        watchdog.tick(self.slot_env(), self.watch, ready_since=ready_since, idle_lanes=idle_lanes)

    def wait_slot(self, why: str, *, stop: Callable[[], bool], sleep: Callable[[float], object], poll: tuple[float, float],
                  on_wait: Callable[[int], None], prio: int) -> tuple[str, str, BeadId] | None:
        return slots_line.wait_slot(self.slot_env(), why, stop=stop, sleep=sleep, poll=poll, on_wait=on_wait, prio=prio)

    def lease(self, store: Beads, slot_bead: BeadId | None, every: float) -> LeaseHandle:
        return Lease(store, slot_bead, every=every)

    def release(self, name: str) -> None:
        SlotPool(self.slot_env()).slot(name).release(mine=True)

    def leaked(self) -> list[str]:
        return [s.name for s in SlotPool(self.slot_env()).leaked()]

    def release_leaked(self, name: str) -> None:
        SlotPool(self.slot_env()).slot(name).release(mine=False)

    def worktree_path(self, repo: str, name: str) -> str:
        return owned.loop_path(repo, name)


class EngineAsks:
    def __init__(self, cfgdir: ConfigDir, now: Callable[[], float]) -> None:
        self.cfgdir, self.now = cfgdir, now

    def held(self, b: Bead) -> bool:
        return parks.gate(self.cfgdir, b, now=self.now()) is not None

    def skip_of(self, b: Bead) -> Skip | None:
        return parks.skip_of(self.cfgdir, b, now=self.now())

    def profile_ahead(self, b: Bead, run: str, why: str) -> None:
        parks.profile_ahead(self.cfgdir, b, run, self.now(), why)

    def promote_if_due(self, store: Beads, per_day: int, now: float, last: float, say: Callable[[str], object]) -> float:
        return deferral.promote_if_due(store, per_day, now, last, say)
