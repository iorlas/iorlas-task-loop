"""The loop's stage adapters and world-facing rules: slots, asks, claims, handover and quiet-moment chores.
The composition roots bind real stage calls; these rules consume ports and callbacks."""
import contextlib
import os
import sys
from collections.abc import Callable, Iterable, Mapping

from jsonl_log import close_held
from tlasks import deferral, parks
from tlasks.contracts.records import AsksHost
from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, Beads
from tlkernel.branches import task_branch
from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.landed import Landed
from tlkernel.loop import Skip
from tlkernel.paths import ConfigDir
from tlkernel.procport import Child, Spawner
from tlkernel.run import ReexecNote
from tlkernel.slots import SlotFail, SlotGitError
from tlslots import aside, owned, watchdog
from tlslots import line as slots_line
from tlslots.env import SlotEnv
from tlslots.lease import Lease
from tlslots.pool import SlotPool
from tlslots.reset import setup

from taskloop.app.loop.env import ReloadNote
from taskloop.app.loop.ports import LeaseHandle


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
    def __init__(self, cfgdir: ConfigDir, now: Callable[[], float], asks_host: Callable[[], AsksHost]) -> None:
        self.cfgdir, self.now, self.asks_host = cfgdir, now, asks_host

    def held(self, b: Bead) -> bool:
        return parks.gate(self.asks_host(), self.cfgdir, b, now=self.now()) is not None

    def skip_of(self, b: Bead) -> Skip | None:
        return parks.skip_of(self.asks_host(), self.cfgdir, b, now=self.now())

    def profile_ahead(self, b: Bead, run: str, why: str) -> None:
        parks.profile_ahead(self.cfgdir, b, run, self.now(), why)

    def promote_if_due(self, store: Beads, per_day: int, now: float, last: float, say: Callable[[str], object]) -> float:
        return deferral.promote_if_due(store, per_day, now, last, say)


STOP_GRACE_S = 300.0  # let a stopped run-task finish its close before ending the stream


def reload_note(read: Callable[[], ReexecNote | None], drop: Callable[[], None]) -> ReloadNote | None:
    rec = read()
    drop()
    if not rec:
        return None
    return ReloadNote(run=rec.run, to=rec.to, frm=rec.frm, from_dir=rec.from_dir, t=rec.t)


def fetch(repo: str, git: Git) -> None:
    with contextlib.suppress(SlotGitError):
        git.fetch(repo)


def chores[Config, Store](lanes: Callable[[], object], config: Callable[[], Config], sweep: Callable[[Config], object],
                          wake: Callable[[Config], object], reflect: Callable[[], object], backup: Callable[[], object],
                          disk: Callable[[], object], store: Store | None, nightly: Callable[[Store], Iterable[str]],
                          say: Callable[[str], object]) -> None:
    lanes()
    cfg = config()
    sweep(cfg)
    wake(cfg)
    try:
        reflect()
    except Exception as e:
        say(f"loop: reflect digest: {e}")
    try:
        backup()
    except Exception as e:
        say(f"loop: db backup: {e}")
    disk()
    if store is not None:
        try:
            for line in nightly(store):
                say(line)
        except Exception as e:
            say(f"loop: bd backup: {e}")


def claim(admit: Callable[[], tuple[bool, str]], take: Callable[[], int]) -> tuple[bool, str]:
    # a paused run's claim was released by the step's sweep; a live claim stops here
    ok, why = admit()
    if not ok:
        return False, why
    return take() == 0, "claimed by another session"


def stop_now(child: Child) -> None:
    child.stop_async(STOP_GRACE_S)


def stop_tree(child: Child) -> None:
    child.stop(STOP_GRACE_S)


def exec_into(repo: str, start_cwd: str, argv: Callable[[], list[str]], environ: Callable[[], Mapping[str, str]]) -> None:
    if start_cwd:
        os.chdir(start_cwd)  # a relative --repo in argv means the start directory
    sys.stdout.flush()
    sys.stderr.flush()
    close_held()
    try:
        cmd = argv()
        os.execve(cmd[0], cmd, environ())
    except OSError:
        with contextlib.suppress(OSError):
            os.chdir(repo)
        raise


def loop_lock(wt: str, slot: str, slot_bead: str | None, bead: str, lock: Callable[[str, str, str, str], object]) -> None:
    if os.path.isdir(wt):
        lock(wt, slot, slot_bead or "", bead)


def available_mb(system: Callable[[], str], spawner: Spawner, parse: Callable[[str], int | None]) -> int | None:
    if system() != "Darwin":
        return None  # macOS only: vm_stat is the one reader
    try:
        result = spawner.run(["/usr/bin/vm_stat"], timeout_s=2)
        return parse(result.out) if result.exit == 0 else None
    except OSError:
        return None


def landed_on_base(repo: str, wt: str, bead_id: BeadId, git: Git, base_of: Callable[[], str],
                   record: Callable[[], Landed | None], peek: Callable[[], Bead | None]) -> bool:
    """Only positive evidence lets the loop treat a bead as landed; an unknown probe stays not ready."""
    if not os.path.isdir(wt):
        return False
    base = base_of()
    rec = record()
    if rec is not None:
        return git.is_ancestor(wt, rec.sha, base)
    branch = getattr(peek(), "metadata", {}).get("branch") or task_branch(bead_id)
    with contextlib.suppress(SlotGitError):
        git.fetch(wt)
    tip = git.rev_parse(wt, "refs/heads/" + branch)
    last = git.log(wt, [tip], limit=1) if tip else []
    if not last or not last[0].subject.endswith(f"({bead_id})"):
        return False
    return git.is_ancestor(wt, tip, base)
