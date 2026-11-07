"""The run-task entry: the slot or worktree a run takes, the admission of its bead (a blocked one reopened), and the one outcome line."""
import contextlib
import signal
import sys
import threading
import time
import uuid
from argparse import Namespace
from collections.abc import Generator
from pathlib import Path
from typing import Any

from tlasks import admission, setup_retry
from tlkernel import childenv, fence
from tlkernel.bead import Bead
from tlkernel.beadsport import BeadPatch, Beads
from tlkernel.config import EngineConfig
from tlkernel.enums import Result
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.fence import SLOT_GEN
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.procport import Spawner
from tlkernel.run import Reexec, RunReport
from tlkernel.run_slot import RUN_SLOT
from tlpipeline.api import admission as pipeline_admission
from tlpipeline.api import target
from tlslots import config as wslots_config
from tlslots import engine_lock

from taskloop.adapters import beadtools, gitrepo, ident
from taskloop.adapters import halt as halting
from taskloop.app.loop.queue import has_areas
from taskloop.app.reconcile import leases
from taskloop.app.run import preflight, running
from taskloop.app.run.engine import Blocked, Engine
from taskloop.app.track import console, verbs
from taskloop.app.track.outcome_line import append_output, pause_line, report
from taskloop.app.wire import asks as wasks
from taskloop.app.wire import slotfx
from taskloop.app.wire import slots as wslots
from taskloop.stores.real import real_stores

say = console.say
TL_PY = Path(__file__).resolve().parents[4] / "skills" / "task-loop" / "tl.py"


def main(a: Any, store: Any = None, *, env: Env, spawner: Spawner, git: Git, who: Identity) -> Any:
    try:
        a.id = target.resolve(a, spawner, gitrepo.repo_root())
    except ValueError as err:
        print(f"tl run-task: {err}", file=sys.stderr)
        return 2
    try:
        rc = run_main(a, store, env=env, spawner=spawner, git=git, who=who)
    except Blocked as b:  # a stop (SIGTERM) before the engine ran: the slot and the lock are already given back
        rc = RunReport(outcome=Result.FAILED, bead=a.id, why=b.why, kind=b.kind.value)
    if isinstance(rc, RunReport):  # stopped before the engine ran: nothing in the bead changed
        report(a, rc)
        return 1
    return rc


def run_main(a: Any, store: Any = None, *, env: Env, spawner: Spawner, git: Git, who: Identity) -> Any:
    with halting.halt_on_sigterm():
        return run_main_stoppable(a, store, env=env, spawner=spawner, git=git, who=who)


def run_main_stoppable(a: Any, store: Any = None, *, env: Env, spawner: Spawner, git: Git, who: Identity) -> Any:
    for f in (sys.stdout, sys.stderr):
        append_output(f)
    if not who.session:  # nobody drives this run: it acts under a session id of its own
        env = env.with_(EnvVar.TASK_LOOP_SESSION, "engine-" + uuid.uuid4().hex[:12])
        who = ident.identity(env)
    repo = gitrepo.repo_root()
    cfg = wslots_config.load_cfg(repo, git)
    if not a.dry_run:
        setup_retry.retry_setup(real_stores(who.config).asks, store or beadtools.bd_store(who.actor, repo),
                                a.id, ident.plugin_version(), time.time(), cfg, starting=True)
    if a.slot == "any":
        return run_any_slot(a, repo, cfg, store, env=env, spawner=spawner, git=git, who=who)
    return run_in(a, repo, cfg, store, env=env, spawner=spawner, git=git, who=who)


def run_any_slot(a: Any, repo: Any, cfg: Any, store: Any = None, *, env: Env, spawner: Spawner, git: Git, who: Identity) -> Any:
    """--slot any: the next free slot, taken in the repo's slot line (first come, first served; --wait: wait in it),
    run there as `--slot NAME`, given back at the end."""
    if a.dry_run:
        return preview(a, repo, cfg, "", store=store, env=env, git=git, who=who)
    cfg_slots = wslots_config.profile_slots(repo)
    if why := wslots.uninitialised(repo, cfg_slots, store, spawner=spawner, git=git, who=who):
        print(f"TAKEN: {why}")
        return RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
    wait = bool(getattr(a, "wait", False))
    told: list[int] = []

    def waiting(ahead: int) -> None:
        if not told:
            say("no free slot{}; waiting in line".format(f" ({ahead} ahead)" if ahead else ""))
            told.append(1)
    halt = halting.RUN_HALT["ev"] or threading.Event()
    got = wslots.wait_slot(repo, cfg_slots, "run-task " + a.id, stop=lambda: not wait or halt.is_set(), sleep=halt.wait,
                           on_wait=waiting, prio=wslots.bead_priority(repo, a.id, who,
                               store), store=store, spawner=spawner, git=git, who=who)
    if not got and halt.is_set():
        raise Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)  # run_bead's caller reports it; no slot was taken
    if not got:
        why = "no free slot (tl slot list); --wait waits in line for one"
        print(f"TAKEN: {why}")
        return RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
    a.slot, a.worktree, sb = got
    a.slot_gen = fence.gen_of(beadtools.peek(store or beadtools.bd_store(who.actor, repo), sb), SLOT_GEN)  # the lease this run took
    RUN_SLOT["owned"] = a.slot  # a re-exec hands the slot on (TL_REEXEC) and its next run-task gives it back
    try:  # run_in sees the slot as taken (its Env names the slot's bead); the engine heartbeats it
        return run_in(a, repo, cfg, store, env=env.with_(EnvVar.TASK_LOOP_SLOT_BEAD, sb), spawner=spawner, git=git, who=who)
    finally:
        with _sigterm_ignored():
            wslots.release_slot(repo, a.slot, bead=a.id, mine=True, store=store, gen=a.slot_gen, spawner=spawner, git=git, who=who)


def take_area(a: Any, repo: Any, cfg: Any, lock: Any, git: Git, who: Identity, sb: Any = "", store: Any = None) -> Any:
    """The engine lock, with the area check before it under the area lock (running.area_lock): "" when this run holds the
    worktree, else why not. A bead whose area runs elsewhere: a warning, or refused with --exclusive-area."""
    def mark() -> None:  # the slot says which bead runs in it (held_bead makes its area busy): only once the area is decided
        if sb:
            beadtools.attempt((store or beadtools.bd_store(who.actor, repo)).update, sb, BeadPatch(set_metadata={"held_bead": a.id}))
    if not has_areas(cfg):
        why = lock.take()
        if not why:
            mark()
        return why
    with running.area_lock(repo, who):
        bead = beadtools.peek(store or beadtools.bd_store(who.actor, repo), a.id) or Bead(id=a.id, title="", status="")
        _area, busy = running.area_busy(repo, cfg, bead, git, who)
        if busy and getattr(a, "exclusive_area", False):
            return busy + " (--exclusive-area)"
        if busy:
            say(f"⚠ {busy}: running anyway beside it; --exclusive-area refuses instead")
        why = lock.take()
        if not why:
            mark()
        return why


def _handed_slot(slot: Any, env: Env) -> Any:
    """True when TL_REEXEC (set by the run-task that exec'd into this one, not yet read by the Engine) says it took `slot` itself."""
    handed = Reexec.parse(env.get(EnvVar.TL_REEXEC))
    return handed is not None and handed.owned == slot


def _worktree_of(a: Any, repo: Any, spawner: Spawner, env: Env, who: Identity) -> tuple[str, Any]:
    """(worktree, failure): the directory the run works in (the slot's, the named one, or a new one), or the outcome that says why none."""
    wt = a.worktree
    if not wt and a.slot:  # the slot is the worktree
        wt = wslots_config.slot_dir(repo, a.slot, wslots_config.profile_slots(repo))
    if not wt:
        r = spawner.run([*childenv.script_argv(TL_PY, env), "worktree", "start"], extra=childenv.identity_env(who))
        wt = r.out.strip().splitlines()[-1] if r.exit == 0 and r.out.strip() else ""
        if not wt:
            print("tl: no worktree: " + r.err, file=sys.stderr)
            return "", RunReport(outcome=Result.FAILED, bead=a.id, why="failed: no worktree: " + r.err[-300:])
    wt = str(Path(wt).resolve())
    if (Path(wt) / ".git").is_dir():  # the main checkout holds the bead database and the config: never a worker's cwd
        print(f"tl: {wt} is the main checkout; run a task in a slot or a worktree (tl slot / tl worktree start)",
              file=sys.stderr)
        return "", RunReport(outcome=Result.FAILED, bead=a.id, why=f"failed: {wt} is the main checkout")
    return wt, None


def _slot_taken(a: Any, repo: Any, wt: str, slot: str, sb: BeadId | None, store: Any, env: Env,
                spawner: Spawner, git: Git, who: Identity) -> tuple[BeadId | None, Any]:
    """(slot bead taken here, taken outcome): a hand run takes its slot's bead as the loop does; one the loop started has it already."""
    named = sb is not None and env.bead(EnvVar.TASK_LOOP_SLOT_BEAD) == sb
    if slot and sb and named and _handed_slot(slot, env):
        RUN_SLOT["owned"] = slot
        return sb, None  # exec'd by the run-task that took this slot: it is still ours, and this process gives it back
    if slot and not (sb and named):
        took, why = wslots.take_named_slot(repo, slot, wslots_config.profile_slots(repo), "run-task " + a.id, store=store, spawner=spawner,
            git=git, who=who)
        if not took:
            print(f"TAKEN: {why}")
            return None, RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
        RUN_SLOT["owned"] = slot
        return took, None
    return None, None


@contextlib.contextmanager
def _sigterm_ignored() -> Generator[None]:
    """A give-back in a finally block is not cut short by a SIGTERM (only the main thread can set the handler)."""
    old = signal.signal(signal.SIGTERM, signal.SIG_IGN) if hasattr(signal, "SIGTERM") and \
        threading.current_thread() is threading.main_thread() else None
    try:
        yield
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)


def run_in(a: Any, repo: Any, cfg: Any, store: Any = None, *, env: Env, spawner: Spawner, git: Git, who: Identity) -> Any:
    if a.dry_run:
        wt = a.worktree or (wslots_config.slot_dir(repo, a.slot, wslots_config.profile_slots(repo)) if a.slot else "")
        return preview(a, repo, cfg, str(Path(wt).resolve()) if wt else "", store=store, env=env, git=git, who=who)
    wt, failed = _worktree_of(a, repo, spawner, env, who)
    if failed:
        return failed
    took, slot = "", ""
    held = engine_lock.HeldLock()
    acquired: engine_lock.EngineLock | None = None
    try:
        # a hand run takes its slot's bead as the loop does (a --worktree that is a slot too); one the loop started has
        # it already: TASK_LOOP_SLOT_BEAD names that very slot's bead
        slot = a.slot or wslots.slot_of(repo, wt, who, store)
        sb_row = wslots.slot_bead(repo, slot, who, store) if slot else None
        sb = sb_row.id if sb_row else None
        took, taken = _slot_taken(a, repo, wt, slot, sb, store, env, spawner, git, who)
        if taken:
            return taken
        if took:
            a.slot_gen = fence.gen_of(beadtools.peek(store or beadtools.bd_store(who.actor, repo), took), SLOT_GEN)
        env = env.with_(EnvVar.TASK_LOOP_SLOT_BEAD, took) if took else env  # the engine's heartbeat keeps it
        lock = engine_lock.EngineLock(who.config, wt, a.id, slot, env, fx=slotfx.FX)
        busy = take_area(a, repo, cfg, lock, git, who, took or sb if slot else "", store)
        if busy:
            why = busy if busy.startswith("area ") else f"worktree {wt}: {busy}"
            print(f"TAKEN: {why}")
            return RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
        acquired = lock
        held.set(lock)
        return run_bead(a, repo, cfg, wt, store, env=env, spawner=spawner, git=git, who=who, held=held)
    finally:
        with _sigterm_ignored():
            if acquired is not None:
                acquired.release()
                held.clear()
            if took:
                wslots.release_slot(repo, slot, bead=a.id, mine=True, store=store, gen=getattr(a, "slot_gen", None), spawner=spawner,
                    git=git, who=who)


defer_stop = halting.stop_deferred  # no state: also before an Engine exists


def preview(a: Namespace, repo: str, cfg: EngineConfig, wt: str, *, store: Beads | None = None,
            env: Env, git: Git, who: Identity) -> int:
    slot = a.slot or (wslots.slot_of(repo, wt, who, store) if wt else "")
    why = preflight.inspect(a.id, wt, repo, cfg, git=git, who=who, env=env, requested=getattr(a, "stage", None),
                            fresh=bool(getattr(a, "fresh", False)), force=bool(getattr(a, "force", False)),
                            continuous=bool(getattr(a, "loop", False)), dry=True, slot=slot)
    if why:
        say(f"refused: {why}")
    return 1 if why else 0


def run_bead(a: Any, repo: Any, cfg: Any, wt: Any, store: Any = None, *, env: Env, spawner: Spawner, git: Git, who: Identity,
             held: engine_lock.HeldLock | None = None) -> Any:
    if a.dry_run:
        return preview(a, repo, cfg, wt, store=store, env=env, git=git, who=who)
    if getattr(a, "stage", None) and not getattr(a, "loop", False):
        why = preflight.inspect(a.id, wt, repo, cfg, git=git, who=who, env=env, requested=getattr(a, "stage", None),
                                fresh=bool(getattr(a, "fresh", False)), force=bool(getattr(a, "force", False)),
                                continuous=False, dry=False, slot=a.slot or "")
        if why:
            say(f"refused: {why}")
            return RunReport(outcome=Result.FAILED, bead=a.id, why=why)
    # a stop during the sweep, admit and claim waits for them, then the engine closes the run as stopped (trace, bead)
    with defer_stop(None) as stop:
        why = pipeline_admission.enter(a.id,
            release_dead=lambda: admission.release_dead(wasks.host(), repo, git, who, store, release=leases.release_dead,
                                                        running_now=running.running, say=say),
            parked=lambda: admission.parked(wasks.host(), a.id, bool(getattr(a, "fresh", False)), repo, who, store),
            admit=lambda: admission.admit(wasks.host(), a.id, repo, git, who, store, fresh=bool(getattr(a, "fresh", False)),
                                         owner_author=cfg.owner_author, running_now=running.running),
            claim=lambda: verbs.claim(who, a.id, store or beadtools.bd_store(who.actor, repo), git, wt, a.slot),
            say=say, taken=print)
        if why is not None:
            return RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
        claim = fence.take(
            store or beadtools.bd_store(who.actor),
            a.id,
            who.actor,
            env.bead(EnvVar.TASK_LOOP_SLOT_BEAD),
            getattr(a, "slot_gen", None),
        )
        eng = Engine(
            a.id,
            wt,
            cfg,
            dry_run=a.dry_run,
            verbose=not getattr(a, "quiet", False),
            fresh=bool(getattr(a, "fresh", False)),
            store=store,
            claim=claim,
            held_lock=held,
            env=env,
            spawner=spawner,
            git=git,
            who=who,
            mode="loop" if getattr(a, "loop", False) else f"stage:{a.stage}" if getattr(a, "stage", None) else "auto-next",
        )
        eng.stop_pending = bool(stop)
        say(f"engine log: {eng.log_path}")
    rc = eng.run(stage=getattr(a, "stage", None), continuous=bool(getattr(a, "loop", False)))
    with defer_stop(None):  # the outcome line is what the loop reads: a stop waits for it
        rec = eng.result()
        if pause_line(rec, eng.retry_after):
            say(pause_line(rec, eng.retry_after))
        report(a, rec)
    return rc
