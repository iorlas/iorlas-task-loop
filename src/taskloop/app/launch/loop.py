"""The loop's composition root: builds the LoopEnv (app/loop) from the engine, delegate and the repo, and readies the process for
`tl loop`. The verbs that print and run are src/taskloop/cli/loop_cmd.py; the loop itself is src/taskloop/app/loop; nothing here decides
anything."""

import contextlib
import os
import shutil
import sys
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from taskloop.adapters import applog, beadtools, childenv, ident, pidcheck
from taskloop.adapters import delegate as dg
from taskloop.adapters import storm as storm_file
from taskloop.adapters.git import REAL
from taskloop.adapters.locks import hold_path
from taskloop.app.asks import sweeps as ask_sweeps
from taskloop.app.doctor import profiles
from taskloop.app.loop import lintrun
from taskloop.app.loop.env import LoopEnv, ReloadNote, Storm
from taskloop.app.loop.files import LoopFiles
from taskloop.app.loop.loop import parse_handover
from taskloop.app.loop.versions import Installs
from taskloop.app.prune import verb as prune_verb
from taskloop.app.reconcile import leases
from taskloop.app.release import catalog, pins, reexec, seams, shell
from taskloop.app.report import reflect
from taskloop.app.run import console, entry
from taskloop.app.run.running import area_lock, running
from taskloop.app.slots import engine_lock
from taskloop.app.track import trail, verbs
from taskloop.app.wire import asks as wasks
from taskloop.app.wire import lanes as wlanes
from taskloop.app.wire import real
from taskloop.app.wire import slots as wslots
from taskloop.contracts import env as penv
from taskloop.contracts import paths
from taskloop.contracts.config import RepoProfile
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ids import BeadId
from taskloop.contracts.landed import LandedStore
from taskloop.contracts.loop import LoopState
from taskloop.contracts.ports import Beads, Child, Git, Hold, Spawner
from taskloop.contracts.slots import SlotGitError
from taskloop.contracts.stores import ReposStore
from taskloop.domain import outcome as oc
from taskloop.domain.beads import rules as beadlint

STOP_GRACE_S = 300.0  # a stopped run-task is given this long to run its close step before stream-proc ends it
HERE = ident.PLUGIN_ROOT / "skills" / "task-loop"  # the install this code runs from; tl.main takes it as a parameter for a test


def cfgdir() -> paths.ConfigDir:
    return paths.ConfigDir(ident.config_dir())



def profile_of(repo: str) -> RepoProfile:
    return wslots.cfg_source(repo)[0]


def prune_repos(repo: str) -> list[str]:
    """The repos `tl prune` looks after: this one and every registered one."""
    known = profiles.registered(ReposStore(cfgdir()))
    return [repo, *(r for r in known if Path(r).resolve() != Path(repo).resolve())]


def bd_of(repo: str) -> Beads:
    return beadtools.bd_store(repo)


def free_bytes() -> int:
    return shutil.disk_usage(ident.config_dir()).free


def files_of(repo: str, now: Callable[[], float] = trail.now) -> LoopFiles:
    return LoopFiles(cfgdir(), wslots.repo_key(repo), pidcheck.pid_alive, now)


def live_loops(repo: str) -> list[LoopState]:
    return files_of(repo).live()


def delegate_route(repo: str | Path) -> str | None:
    """The route.py of the delegate this repo's engine would use (its `delegate` config, the pin, the install), or None."""
    res = seams.resolve_delegate(wslots.load_cfg(str(repo)).delegate)
    return res.route if isinstance(res, dg.Resolved) else None


def roles(repo: str | Path, env: Env) -> dict[str, bool | None] | None:
    route = delegate_route(repo)
    if not route:
        return None
    return {role: v.get("usable") if isinstance((v or {}).get("usable"), bool) else None for role, v in dg.role_status(route, env).items()}


def make_probe(repo: str | Path) -> dg.RouteProbe | None:
    route = delegate_route(repo)
    return dg.RouteProbe(route) if route else None


def storm(repo: str, now: Callable[[], float] = trail.now, git: Git = REAL) -> Storm | None:
    rid = git.remote_url(repo, "origin") or repo
    path = storm_file.storm_path(ident.config_dir(), rid)
    rec = storm_file.read_storm(path, now(), oc.KNOBS["storm_window_s"])
    if not rec:
        return None
    banner = (
        "STOPPED: storm {} on {}; the beads stay open (look at their logs). Record {} expires {:d} min after it was written; "
        "delete it to start sooner"
    ).format(rec.get("fingerprint"), ",".join(rec.get("beads") or []), path, (oc.KNOBS["storm_window_s"] // 60))
    return Storm(rec.get("fingerprint") or "", banner)


def landed_on_base(repo: str, store: Beads, wt: str, bead_id: BeadId, git: Git = REAL) -> bool:
    """True when the bead's landed record names a sha that is on the base. LEGACY, only for a bead with no record (landed before
    0.23.179): its land commit (titled `... (<id>)`) is the tip of its branch and already on the base; this can go with them."""
    if not os.path.isdir(wt):
        return False
    base = wslots.load_cfg(repo).base
    rec = LandedStore(paths.ConfigDir(ident.config_dir())).get(bead_id)
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


def reload_note(bead: BeadId) -> ReloadNote | None:
    rec = reexec.read_reexec(bead)
    reexec.drop_reexec(bead)
    if not rec:
        return None
    return ReloadNote(run=rec.run, to=rec.to, frm=rec.frm, from_dir=rec.from_dir, t=rec.t)


def fetch(repo: str, git: Git = REAL) -> None:
    with contextlib.suppress(SlotGitError):
        git.fetch(repo)


def release_dead(repo: str, store: Beads, now: float) -> list[str]:
    return leases.release_dead(repo, store, running(repo, store), ident.hostname(), now)


def chores(repo: str, spawner: Spawner) -> None:
    wlanes.chore(console.say, spawner)  # delegate's lane status filed again when the snapshot is 20 min old (the dash reads the file)
    wasks.sweep_asks(console.say, wslots.load_cfg(repo))  # asks of closed beads closed, unanswered ones parked, answers no run used flagged
    try:
        reflect.maybe_run(spawner)  # the run reflections into beads, once a day (tl-bl5)
    except Exception as e:
        console.say(f"loop: reflect digest: {e}")


def claim(repo: str, store: Beads, bead: BeadId, wt: str, slot: str, now: Callable[[], float] = trail.now) -> tuple[bool, str]:
    ok, why = entry.admit(bead, repo, store, now())  # a paused run's claim was released by the step's sweep; a live claim stops here
    if not ok:
        return False, why
    return verbs.claim(bead, wt, slot, store=store) == 0, "claimed by another session"


def spawn(spawner: Spawner, cmd: list[str], log: Any, extra: Mapping[str, str]) -> tuple[Child, Hold]:
    """run-task as a child in its own process group: Ctrl-C to the loop reaches it only as the loop's SIGTERM.
    -> (the child, the hold of its spawn): the caller replays the hold first inside the try that stops the child."""
    return spawner.start_held(cmd, out=log, extra=extra)


def stop_now(child: Child) -> None:
    child.stop_async(STOP_GRACE_S)


def stop_tree(child: Child) -> None:
    child.stop(STOP_GRACE_S)


def exec_into(repo: str, d: Path, argv: list[str], handover: str, start_cwd: str = "") -> None:
    penv.export(EnvVar.TL_LOOP_STATE, handover)
    if start_cwd:
        os.chdir(start_cwd)  # cmd_loop chdir'd into the repo; a relative --repo in argv means the start directory
    sys.stdout.flush()
    sys.stderr.flush()
    applog.close_all()
    try:
        cmd = [*childenv.script_argv(d / "skills" / "task-loop" / "tl.py"), *argv]
        os.execv(cmd[0], cmd)
    except OSError:
        penv.take(EnvVar.TL_LOOP_STATE)
        with contextlib.suppress(OSError):
            os.chdir(repo)
        raise


def loop_lock(wt: str, slot: str, slot_bead: str | None, bead: str) -> None:
    if os.path.isdir(wt):
        engine_lock.loop_lock(wt, slot, slot_bead or "", bead=bead)


def build(repo: str, store: Beads | None = None, session_actor: str = "", here: Path = HERE, now: Callable[[], float] = trail.now,
          start_cwd: str = "", *, env: Env, spawner: Spawner) -> LoopEnv:
    """The LoopEnv of `repo` on this install."""
    store = store or beadtools.bd_store(repo)
    cfg = cfgdir()

    def profile() -> RepoProfile:
        return profile_of(repo)

    return LoopEnv(
        repo=repo,
        repo_key=wslots.repo_key(repo),
        cfgdir=cfg,
        store=store,
        slot_env=lambda: wslots.slot_env(repo, store, profile().slots, now, spawner=spawner),
        profile=profile,
        fetch=lambda: fetch(repo),
        lint=lambda b: beadlint.why(b, repo, lambda: lintrun.has_children(store, b.id)),
        running=lambda: running(repo, store),
        area_lock=lambda: area_lock(repo),
        wt_lock=lambda key: hold_path(cfg.lock_record(LockWhat.WORKTREE.value, key), f"pid {os.getpid()}", what=LockWhat.WORKTREE),
        start_worktree=lambda name: wslots.start_worktree(repo, name),
        claim=lambda b, wt, slot: claim(repo, store, b, wt, slot, now),
        loop_lock=loop_lock,
        drop_engine_lock=lambda d: engine_lock.drop_engine_lock(d, os.getpid()),
        spawn=lambda cmd, log, extra: spawn(spawner, cmd, log, extra),
        stop_now=stop_now,
        stop_tree=stop_tree,
        run_task_argv=lambda bead, wt, slot, out, code: (
            [*childenv.script_argv((code or here) / "tl.py"), "run-task", bead, "--worktree", wt, "--outcome-file", out]
            + (["--slot", slot] if slot else [])
        ),
        landed_on_base=lambda wt, bead: landed_on_base(repo, store, wt, bead),
        reload_note=reload_note,
        chores=lambda: chores(repo, spawner),
        release_dead=lambda: release_dead(repo, store, now()),
        ask_lines=lambda: ask_sweeps.orphan_lines(wasks.store()),
        storm=lambda: storm(repo, now),
        probe=lambda: make_probe(repo),
        roles=lambda: roles(repo, env),
        has_delegate=lambda: bool(delegate_route(repo)),
        event=trail.event,
        pid_alive=pidcheck.pid_alive,
        behind=catalog.releases_behind,
        version=here.parents[1].name,
        code_dir=str(here),
        session_actor=session_actor,
        actor=ident.actor,
        exec_into=lambda d, argv, handover: exec_into(repo, d, argv, handover, start_cwd),
        take_handover=lambda: penv.take(EnvVar.TL_LOOP_STATE),
        say=console.say,
        now=now,
        pid=os.getpid(),
        prune=lambda say: prune_verb.run(cfg, profile().loop, prune_repos(repo), lambda r: store if r == repo else bd_of(r),
                                         now(), False, shell.of(spawner, real.git(), env), say),
        free_bytes=free_bytes,
    )


def installs(cfg: paths.ConfigDir, here: Path = HERE, now: Callable[[], float] = trail.now) -> Installs:
    """The installs of task-loop on this machine."""
    return Installs(cfg, here.parents[1], lambda: catalog.installed_version("task-loop"), lambda: pins.read_pin().task_loop or "",
                    now=now)


def newer(here: Path = HERE) -> tuple[str, Path] | None:
    """(version, dir) of the install the loop would move to, or None: the engine's step-boundary look."""
    t = installs(cfgdir(), here=here).move_to()
    return (t.version, t.dir) if t else None


def other_red_rows(repo: str) -> list[str]:
    """The red rows of the other registered repos' bad profiles (`tl loop status` shows them; nothing else changes)."""
    return profiles.red_rows(profiles.registered(ReposStore(cfgdir())), but=repo)


def begin_loop(repo: str, env: Env) -> tuple[str, str]:
    """Make this process the loop of `repo`: its working directory, its own actor. -> (the start directory, the session's actor)."""
    start_cwd = os.getcwd()
    os.chdir(repo)  # every tl helper and bd call works on the current directory's repo
    inherited, _ = parse_handover(
        env.get(EnvVar.TL_LOOP_STATE)
    )  # set when this process is the same loop, exec'd into a newer install
    if not ident.session_id():  # without a Claude session the actor would be per folder: two loops would share it
        penv.export(EnvVar.TASK_LOOP_SESSION, "loop-" + uuid.uuid4().hex[:12])
    # an actor of its own, never the session's: bd lets an actor re-claim its own bead, so two loops (or a loop and a hand run)
    # started from one session would both win one claim. run-task re-claims as this actor (one for both).
    penv.take(EnvVar.TASK_LOOP_ACTOR)
    session = ident.actor()
    penv.export(EnvVar.TASK_LOOP_ACTOR, (inherited.actor if inherited else "") or f"{session}-{uuid.uuid4().hex[:6]}")
    return start_cwd, session


def live_work() -> list[tuple[str, str]]:
    """What runs on this machine: ("loop"|"run", text) for every live loop and every busy engine lock of the registered repos."""
    repos = [r for r in ReposStore(cfgdir()).known() if os.path.isdir(r)]
    out: list[tuple[str, str]] = []
    for r in repos:
        for st in live_loops(r):
            out.append(("loop", "loop pid {} on {}{}".format(st.pid, r, (" running " + st.bead) if st.bead else "")))
        for wt in [r, *wslots.worktrees(r, slots=None if shutil.which("bd") else [])]:  # slot dirs need bd
            busy = engine_lock.engine_busy(wt)
            if busy:
                out.append(("run", f"run in {wt}: {busy}"))
    return out
