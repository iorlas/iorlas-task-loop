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

from tlareas import policy as area_admission
from tlasks import admission, sweeps
from tlkernel import childenv, fence
from tlkernel.beadsport import BeadPatch, Beads
from tlkernel.config import EngineConfig
from tlkernel.enums import Result
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.kinds import Kind
from tlkernel.procport import Spawner
from tlkernel.run import RUN_SLOT, RunReport
from tlpipeline.api import admission as pipeline_admission
from tlpipeline.api import target
from tlslots import config as wslots_config
from tlslots import engine_lock, machine

from taskloop.adapters import beadtools, gitrepo, ident
from taskloop.adapters import halt as halting
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
        sweeps.retry_setup(real_stores(who.config).asks, store or beadtools.bd_store(who.actor, repo),
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
    halt = halting.RUN_HALT["ev"] or threading.Event()
    got = wslots.any_slot(repo, cfg_slots, a.id, bool(getattr(a, "wait", False)), halt, say=console.say, store=store,
                          spawner=spawner, git=git, who=who)
    if isinstance(got, machine.Refused):
        print(f"TAKEN: {got.why}")
        return RunReport(outcome=Result.TAKEN, bead=a.id, why=got.why)
    if isinstance(got, machine.Stopped):
        raise Blocked("failed: stopped (SIGTERM)", kind=Kind.PAUSE_KILLED)
    a.slot, a.worktree, sb = got.slot, got.worktree, got.bead
    a.slot_gen = got.gen
    RUN_SLOT["owned"] = a.slot
    try:  # run_in sees the slot as taken (its Env names the slot's bead); the engine heartbeats it
        return run_in(a, repo, cfg, store, env=env.with_(EnvVar.TASK_LOOP_SLOT_BEAD, sb), spawner=spawner, git=git, who=who)
    finally:
        wslots.give_back(repo, a.slot, a.id, a.slot_gen, store, spawner=spawner, git=git, who=who, guard=_sigterm_ignored)


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
    worktree = wslots.run_worktree(a.worktree, a.slot, a.id, repo, childenv.script_argv(TL_PY, env), spawner, who)
    if worktree.failed:
        return RunReport(outcome=Result.FAILED, bead=a.id, why=worktree.failed)
    wt = worktree.path
    held = engine_lock.HeldLock()
    # A loop-started run already has the slot; a hand run takes its slot's bead here.
    slot = a.slot or wslots.slot_of(repo, wt, who, store)
    sb_row = wslots.slot_bead(repo, slot, who, store) if slot else None
    sb = sb_row.id if sb_row else None
    with wslots.claimed(repo, slot, sb, sb is not None and env.bead(EnvVar.TASK_LOOP_SLOT_BEAD) == sb,
                        "run-task " + a.id, store, env=env, spawner=spawner, git=git, who=who,
                        guard=_sigterm_ignored) as claim:
        took = claim.bead
        if claim.refused:
            print(f"TAKEN: {claim.refused}")
            return RunReport(outcome=Result.TAKEN, bead=a.id, why=claim.refused)
        if took:
            a.slot_gen = claim.gen
        env = env.with_(EnvVar.TASK_LOOP_SLOT_BEAD, took) if took else env  # the engine's heartbeat keeps it
        lock = engine_lock.EngineLock(who.config, wt, a.id, slot, env, fx=slotfx.FX)
        host = running.areas_host(repo, cfg, git, who, store, say)
        held_slot = (took or sb) if slot else None
        def mark() -> None:
            if held_slot:
                beadtools.attempt(host.store.update, held_slot, BeadPatch(set_metadata={"held_bead": a.id}))
        busy = area_admission.hand(host, a.id, getattr(a, "exclusive_area", False), lock.take, mark)
        if busy:
            why = busy if busy.startswith("area ") else f"worktree {wt}: {busy}"
            print(f"TAKEN: {why}")
            return RunReport(outcome=Result.TAKEN, bead=a.id, why=why)
        with engine_lock.held(lock, held, _sigterm_ignored):
            return run_bead(a, repo, cfg, wt, store, env=env, spawner=spawner, git=git, who=who, held=held)


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
