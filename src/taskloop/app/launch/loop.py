"""The loop's composition root: builds the LoopEnv (app/loop) from the engine, delegate and the repo, and readies the process for
`tl loop`. The verbs that print and run are src/taskloop/cli/loop_cmd.py; the loop itself is src/taskloop/app/loop; nothing here decides
anything."""

import functools
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from tlasks import sweeps as ask_sweeps
from tlkernel import childenv, paths
from tlkernel.beadsport import Beads
from tlkernel.config import RepoProfile
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import new_loop_id
from tlkernel.lockenums import LockWhat
from tlkernel.loop import LoopState
from tlkernel.procport import Spawner
from tlkernel.rowstores import ReposStore
from tlrelease import catalog, shell
from tlslots import config as wslots_config
from tlslots import engine_lock

from taskloop.adapters import beadtools, ident, pidcheck
from taskloop.adapters.bd import BdStore
from taskloop.adapters.locks import hold_path
from taskloop.app.doctor import profiles
from taskloop.app.launch import loop_ops as ops
from taskloop.app.loop import lintrun
from taskloop.app.loop.env import LoopEnv
from taskloop.app.loop.files import LoopFiles
from taskloop.app.loop.stages import EngineAsks, EngineSlots
from taskloop.app.prune import verb as prune_verb
from taskloop.app.run.running import area_lock, running
from taskloop.app.track import console, trail
from taskloop.app.wire import asks as wasks
from taskloop.app.wire import slots as wslots
from taskloop.domain.beads import rules as beadlint
from taskloop.stores.delegate import make_probe as make_net_probe
from taskloop.stores.delegate import route_name
from taskloop.stores.real import real_stores

HERE = ident.PLUGIN_ROOT / "skills" / "task-loop"  # the install this code runs from; tl.main takes it as a parameter for a test


def profile_of(repo: str, git: Git) -> RepoProfile:
    return wslots_config.cfg_source(repo, git)[0]


def prune_repos(repo: str, cfg: paths.ConfigDir) -> list[str]:
    """The repos `tl prune` looks after: this one and every registered one."""
    known = profiles.registered(ReposStore(cfg))
    return [repo, *(r for r in known if Path(r).resolve() != Path(repo).resolve())]


def bd_of(who: Identity, repo: str) -> Beads:
    return beadtools.bd_store(who.actor, repo)


def free_bytes(cfg: paths.ConfigDir) -> int:
    return shutil.disk_usage(cfg.root).free


def files_of(repo: str, cfg: paths.ConfigDir, now: Callable[[], float] = trail.now) -> LoopFiles:
    return LoopFiles(cfg, wslots.repo_key(repo), pidcheck.pid_alive, now)


def live_loops(repo: str, cfg: paths.ConfigDir) -> list[LoopState]:
    return files_of(repo, cfg).live()


def delegate_route(repo: str | Path, env: Env, git: Git) -> str | None:
    """What the engine's calls go through: the delegate library."""
    return route_name()


def make_probe(repo: str | Path, env: Env, git: Git):
    return make_net_probe(("github.com",)) if delegate_route(repo, env, git) else None


def build(repo: str, store: Beads | None = None, session_actor: str = "", here: Path = HERE, now: Callable[[], float] = trail.now,
          start_cwd: str = "", *, env: Env, spawner: Spawner, git: Git, who: Identity) -> LoopEnv:
    """The LoopEnv of `repo` on this install."""
    store = store or beadtools.bd_store(who.actor, repo)
    loop_id = env.get(EnvVar.TASK_LOOP_LOOP_ID) or new_loop_id()  # an exec'd loop keeps the id of the lifetime it continues
    env = env.with_(EnvVar.TASK_LOOP_LOOP_ID, loop_id)  # ... and hands it on through its own exec (exec_env)
    cfg = paths.ConfigDir(ident.config_dir(env))  # made here: the loop writes under it for as long as it runs

    def profile() -> RepoProfile:
        return profile_of(repo, git)

    return LoopEnv(
        repo=repo,
        repo_key=wslots.repo_key(repo),
        cfgdir=cfg,
        store=store,
        slots=EngineSlots(lambda: wslots.slot_env(repo, store, profile().slots, now, spawner=spawner, git=git, who=who)),
        asks=EngineAsks(cfg, now, wasks.host),
        profile=profile,
        fetch=lambda: ops.fetch(repo, git),
        lint=lambda b: beadlint.why(b, repo, lambda: lintrun.has_children(store, b.id)),
        running=lambda: running(repo, git, who, store),
        area_lock=lambda: area_lock(repo, who),
        wt_lock=lambda key: hold_path(cfg.lock_record(LockWhat.WORKTREE.value, key), f"pid {os.getpid()}", what=LockWhat.WORKTREE),
        start_worktree=lambda name: wslots.start_worktree(repo, git, who, name),
        claim=lambda b, wt, slot: ops.claim(repo, store, b, wt, slot, git, who, now),
        loop_lock=functools.partial(ops.loop_lock, cfg),
        drop_engine_lock=lambda d: engine_lock.drop_engine_lock(cfg, d, os.getpid()),
        spawn=lambda cmd, log, extra: ops.spawn(
            spawner, cmd, log, {**extra, EnvVar.TASK_LOOP_LOOP_ID.value: loop_id, **childenv.identity_env(who)}),
        stop_now=ops.stop_now,
        stop_tree=ops.stop_tree,
        run_task_argv=lambda bead, wt, slot, out, code: (
            [*childenv.script_argv((code or here) / "tl.py", env), "run-task", bead, "--loop", "--worktree", wt, "--outcome-file", out]
            + (["--slot", slot] if slot else [])
        ),
        landed_on_base=lambda wt, bead: ops.landed_on_base(repo, cfg, store, wt, bead, git),
        reload_note=lambda bead: ops.reload_note(cfg, bead),
        chores=lambda: ops.chores(repo, spawner, env, git, who, store if isinstance(store, BdStore) else None),
        release_dead=lambda: ops.release_dead(repo, store, now(), git, who),
        ask_lines=lambda: ask_sweeps.orphan_lines(wasks.store(cfg)),
        probe=lambda: make_probe(repo, env, git),
        event=functools.partial(trail.event, who),
        pid_alive=pidcheck.pid_alive,
        behind=lambda v: catalog.releases_behind(v, ident.claude_dir(env)),
        version=here.parents[1].name,
        code_dir=str(here),
        session_actor=session_actor,
        actor=lambda: who.actor,
        exec_into=lambda d, argv, handover: ops.exec_into(repo, d, argv, handover, env, who, start_cwd),
        take_handover=lambda: env.get(EnvVar.TL_LOOP_STATE),
        host=real_stores(cfg).host.need,
        say=console.say,
        now=now,
        pid=os.getpid(),
        prune=lambda say: prune_verb.run(
            cfg,
            profile().loop,
            prune_repos(repo, cfg),
            lambda r: store if r == repo else bd_of(who, r),
            now(),
            False,
            shell.of(spawner, git, env),
            say,
            live=lambda r: running(r, git, who, store if r == repo else bd_of(who, r)),
        ),
        free_bytes=lambda: free_bytes(cfg),
        available_mb=lambda: ops.available_mb(spawner),
    )
