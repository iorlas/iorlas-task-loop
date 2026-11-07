"""What the loop does to the world, one verb each: claim a bead, spawn and stop its run-task, exec into a newer install, the chores
of a quiet moment. Each is a function of ports; app/launch/loop.py closes them over a repo into the LoopEnv."""
import contextlib
import os
import platform
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from jsonl_log import close_held

from taskloop.adapters import beadtools, childenv, ident, ram
from taskloop.adapters.bd import BdStore
from taskloop.app.doctor import disk
from taskloop.app.loop.env import ReloadNote
from taskloop.app.reconcile import leases
from taskloop.app.release import reexec
from taskloop.app.report import reflect
from taskloop.app.run import console, entry
from taskloop.app.run.running import running
from taskloop.app.slots import engine_lock
from taskloop.app.track import trail, verbs
from taskloop.app.wire import asks as wasks
from taskloop.app.wire import lanes as wlanes
from taskloop.app.wire import slots as wslots
from taskloop.contracts import bdbackup, factorybackup, paths
from taskloop.contracts.beadsport import Beads
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.gitport import Git
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.landed import landed_by
from taskloop.contracts.procport import Child, Hold, Spawner
from taskloop.contracts.slots import SlotGitError, git_probe

STOP_GRACE_S = 300.0  # a stopped run-task is given this long to run its close step before stream-proc ends it


def reload_note(cfg: paths.ConfigDir, bead: BeadId) -> ReloadNote | None:
    rec = reexec.read_reexec(cfg, bead)
    reexec.drop_reexec(cfg, bead)
    if not rec:
        return None
    return ReloadNote(run=rec.run, to=rec.to, frm=rec.frm, from_dir=rec.from_dir, t=rec.t)


def fetch(repo: str, git: Git) -> None:
    with contextlib.suppress(SlotGitError):
        git.fetch(repo)


def release_dead(repo: str, store: Beads, now: float, git: Git, who: Identity) -> list[str]:
    return leases.release_dead(repo, store, running(repo, git, who, store), ident.hostname(), now)


def chores(repo: str, spawner: Spawner, env: Env, git: Git, who: Identity, store: BdStore | None = None) -> None:
    wlanes.chore(console.say, spawner, env)  # delegate's lane status filed again when the snapshot is 20 min old (the dash reads the file)
    # asks of closed beads closed, unanswered ones parked, answers no run used flagged
    cfg = wslots.load_cfg(repo, git)
    wasks.sweep_asks(who, who.config, console.say, cfg, repo)
    wasks.wake_prs(who, who.config, spawner, cfg, repo)  # a PR-mode land's PR the owner merged or closed: its bead runs again
    try:
        reflect.maybe_run(spawner, env, who.config)  # the run reflections into beads, once a day (tl-bl5)
    except Exception as e:
        console.say(f"loop: reflect digest: {e}")
    try:
        factorybackup.backup(who.config, trail.now())
    except Exception as e:
        console.say(f"loop: db backup: {e}")
    disk.sample_volume(who.config, trail.now(), console.say)  # the hourly point of doctor --disk's forecast
    if store is not None:
        try:
            for line in bdbackup.nightly(who.config, wslots.repo_key(repo), lambda argv: _bd(store, argv), trail.now()):
                console.say(line)
        except Exception as e:
            console.say(f"loop: bd backup: {e}")


def _bd(store: BdStore, argv: list[str]) -> tuple[int, str, str]:
    r = store.passthrough(argv)
    return r.code, r.out, r.err


def claim(repo: str, store: Beads, bead: BeadId, wt: str, slot: str, git: Git, who: Identity,
          now: Callable[[], float] = trail.now) -> tuple[bool, str]:
    # a paused run's claim was released by the step's sweep; a live claim stops here
    ok, why = entry.admit(bead, repo, git, who, store, now())
    if not ok:
        return False, why
    return verbs.claim(who, bead, store, git, wt, slot) == 0, "claimed by another session"


def spawn(spawner: Spawner, cmd: list[str], log: Any, extra: Mapping[str, str]) -> tuple[Child, Hold]:
    """run-task as a child in its own process group: Ctrl-C to the loop reaches it only as the loop's SIGTERM.
    -> (the child, the hold of its spawn): the caller replays the hold first inside the try that stops the child."""
    return spawner.start_held(cmd, out=log, extra=extra)


def stop_now(child: Child) -> None:
    child.stop_async(STOP_GRACE_S)


def stop_tree(child: Child) -> None:
    child.stop(STOP_GRACE_S)


def exec_into(repo: str, d: Path, argv: list[str], handover: str, env: Env, who: Identity, start_cwd: str = "") -> None:
    if start_cwd:
        os.chdir(start_cwd)  # cmd_loop chdir'd into the repo; a relative --repo in argv means the start directory
    sys.stdout.flush()
    sys.stderr.flush()
    close_held()
    try:
        cmd = [*childenv.script_argv(d / "skills" / "task-loop" / "tl.py", env), *argv]
        os.execve(cmd[0], cmd, childenv.exec_env(env, {EnvVar.TL_LOOP_STATE: handover, EnvVar.TASK_LOOP_SESSION: who.session}))
    except OSError:
        with contextlib.suppress(OSError):
            os.chdir(repo)
        raise


def loop_lock(cfg: paths.ConfigDir, wt: str, slot: str, slot_bead: str | None, bead: str) -> None:
    if os.path.isdir(wt):
        engine_lock.loop_lock(cfg, wt, slot, slot_bead or "", bead=bead)


def available_mb(spawner: Spawner) -> int | None:
    if platform.system() != "Darwin":
        return None  # macOS only: vm_stat is the one reader
    try:
        result = spawner.run(["/usr/bin/vm_stat"], timeout_s=2)
        return ram.available_mb(result.out) if result.exit == 0 else None
    except OSError:
        return None


def landed_on_base(repo: str, cfg: paths.ConfigDir, store: Beads, wt: str, bead_id: BeadId, git: Git) -> bool:
    """True when the bead's landed record names a sha that is on the base. LEGACY, only for a bead with no record (landed before
    0.23.179): its land commit (titled `... (<id>)`) is the tip of its branch and already on the base; this can go with them."""
    return git_probe(lambda: _landed_on_base(repo, cfg, store, wt, bead_id, git), False)


def _landed_on_base(repo: str, cfg: paths.ConfigDir, store: Beads, wt: str, bead_id: BeadId, git: Git) -> bool:
    """Only positive evidence lets the loop treat a bead as landed; an unknown probe stays not ready."""
    if not os.path.isdir(wt):
        return False
    base = wslots.load_cfg(repo, git).base
    rec = landed_by(store)(bead_id)
    if rec is not None:
        return git.is_ancestor(wt, rec.sha, base)
    branch = getattr(beadtools.peek(store, bead_id), "metadata", {}).get("branch") or "task/" + bead_id
    with contextlib.suppress(SlotGitError):
        git.fetch(wt)
    tip = git.rev_parse(wt, "refs/heads/" + branch)
    last = git.log(wt, [tip], limit=1) if tip else []
    if not last or not last[0].subject.endswith(f"({bead_id})"):
        return False
    return git.is_ancestor(wt, tip, base)
