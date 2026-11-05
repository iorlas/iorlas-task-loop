"""The loop's composition root: builds the LoopEnv (app/loop) from the engine, delegate and the repo, and readies the process for
`tl loop`. The verbs that print and run are src/taskloop/cli/loop_cmd.py; the loop itself is src/taskloop/app/loop; nothing here decides
anything."""

import contextlib
import functools
import os
import platform
import shutil
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters import beadtools, childenv, ident, pidcheck, ram
from taskloop.adapters import delegate as dg
from taskloop.adapters import storm as storm_file
from taskloop.adapters.locks import hold_path
from taskloop.adapters.repourl import repo_url
from taskloop.app.asks import sweeps as ask_sweeps
from taskloop.app.doctor import profiles
from taskloop.app.launch import loop_ops as ops
from taskloop.app.loop import lintrun
from taskloop.app.loop.env import LoopEnv, Storm
from taskloop.app.loop.files import LoopFiles
from taskloop.app.prune import verb as prune_verb
from taskloop.app.release import catalog, shell, suite
from taskloop.app.run import console
from taskloop.app.run.running import area_lock, running
from taskloop.app.slots import engine_lock
from taskloop.app.track import trail
from taskloop.app.wire import asks as wasks
from taskloop.app.wire import slots as wslots
from taskloop.contracts import paths
from taskloop.contracts.config import HostResources, RepoProfile
from taskloop.contracts.enums import LockWhat
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.identity import Identity
from taskloop.contracts.ids import BeadId
from taskloop.contracts.landed import LandedStore
from taskloop.contracts.loop import LoopState
from taskloop.contracts.ports import Beads, Git, Spawner
from taskloop.contracts.slots import SlotGitError, git_probe
from taskloop.contracts.stores import JsonStore, ReposStore
from taskloop.domain import outcome as oc
from taskloop.domain.beads import rules as beadlint

HERE = ident.PLUGIN_ROOT / "skills" / "task-loop"  # the install this code runs from; tl.main takes it as a parameter for a test


def profile_of(repo: str, git: Git) -> RepoProfile:
    return wslots.cfg_source(repo, git)[0]


def prune_repos(repo: str, cfg: paths.ConfigDir) -> list[str]:
    """The repos `tl prune` looks after: this one and every registered one."""
    known = profiles.registered(ReposStore(cfg))
    return [repo, *(r for r in known if Path(r).resolve() != Path(repo).resolve())]


def bd_of(who: Identity, repo: str) -> Beads:
    return beadtools.bd_store(who.actor, repo)


def free_bytes(cfg: paths.ConfigDir) -> int:
    return shutil.disk_usage(cfg.root).free


def available_mb(spawner: Spawner) -> int | None:
    if platform.system() != "Darwin":
        return suite.available_mb()
    try:
        result = spawner.run(["/usr/bin/vm_stat"], timeout_s=2)
        return ram.available_mb(result.out) if result.exit == 0 else None
    except OSError:
        return None


def files_of(repo: str, cfg: paths.ConfigDir, now: Callable[[], float] = trail.now) -> LoopFiles:
    return LoopFiles(cfg, wslots.repo_key(repo), pidcheck.pid_alive, now)


def live_loops(repo: str, cfg: paths.ConfigDir) -> list[LoopState]:
    return files_of(repo, cfg).live()


def delegate_route(repo: str | Path, env: Env, git: Git) -> str | None:
    """What the engine's calls go through: the delegate library."""
    return dg.resolve().route


def roles(repo: str | Path, env: Env, git: Git) -> dict[str, bool | None] | None:
    route = delegate_route(repo, env, git)
    if not route:
        return None
    return {role: v.get("usable") if isinstance((v or {}).get("usable"), bool) else None for role, v in dg.role_status(env).items()}


def make_probe(repo: str | Path, env: Env, git: Git) -> dg.RouteProbe | None:
    route = delegate_route(repo, env, git)
    return dg.RouteProbe(("github.com",)) if route else None


def storm(repo: str, cfg: paths.ConfigDir, now: Callable[[], float] = trail.now, *, git: Git) -> Storm | None:
    path = storm_file.storm_path(cfg.root, repo_url(git, repo))
    rec = storm_file.read_storm(path, now(), oc.KNOBS["storm_window_s"])
    if not rec:
        return None
    banner = (
        "WAIT: storm {} on {}; the beads stay open (look at their logs). Record {} expires {:d} min after it was written; "
        "clear it to wake sooner"
    ).format(rec.get("fingerprint"), ",".join(rec.get("beads") or []), path, (oc.KNOBS["storm_window_s"] // 60))
    return Storm(rec.get("fingerprint") or "", banner, float(rec["t"]) + oc.KNOBS["storm_window_s"])


def landed_on_base(repo: str, cfg: paths.ConfigDir, store: Beads, wt: str, bead_id: BeadId, git: Git) -> bool:
    """True when the bead's landed record names a sha that is on the base. LEGACY, only for a bead with no record (landed before
    0.23.179): its land commit (titled `... (<id>)`) is the tip of its branch and already on the base; this can go with them."""
    return git_probe(lambda: _landed_on_base(repo, cfg, store, wt, bead_id, git), False)


def _landed_on_base(repo: str, cfg: paths.ConfigDir, store: Beads, wt: str, bead_id: BeadId, git: Git) -> bool:
    """Only positive evidence lets the loop treat a bead as landed; an unknown probe stays not ready."""
    if not os.path.isdir(wt):
        return False
    base = wslots.load_cfg(repo, git).base
    rec = LandedStore(cfg).get(bead_id)
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


def build(repo: str, store: Beads | None = None, session_actor: str = "", here: Path = HERE, now: Callable[[], float] = trail.now,
          start_cwd: str = "", *, env: Env, spawner: Spawner, git: Git, who: Identity) -> LoopEnv:
    """The LoopEnv of `repo` on this install."""
    store = store or beadtools.bd_store(who.actor, repo)
    cfg = paths.ConfigDir(ident.config_dir(env))  # made here: the loop writes under it for as long as it runs

    def profile() -> RepoProfile:
        return profile_of(repo, git)

    return LoopEnv(
        repo=repo,
        repo_key=wslots.repo_key(repo),
        cfgdir=cfg,
        store=store,
        slot_env=lambda: wslots.slot_env(repo, store, profile().slots, now, spawner=spawner, git=git, who=who),
        profile=profile,
        fetch=lambda: ops.fetch(repo, git),
        lint=lambda b: beadlint.why(b, repo, lambda: lintrun.has_children(store, b.id)),
        running=lambda: running(repo, git, who, store),
        area_lock=lambda: area_lock(repo, who),
        wt_lock=lambda key: hold_path(cfg.lock_record(LockWhat.WORKTREE.value, key), f"pid {os.getpid()}", what=LockWhat.WORKTREE),
        start_worktree=lambda name: wslots.start_worktree(repo, git, who, name),
        claim=lambda b, wt, slot: ops.claim(repo, store, b, wt, slot, git, who, now),
        loop_lock=ops.loop_lock,
        drop_engine_lock=lambda d: engine_lock.drop_engine_lock(d, os.getpid()),
        spawn=lambda cmd, log, extra: ops.spawn(spawner, cmd, log, {**extra, **childenv.identity_env(who)}),
        stop_now=ops.stop_now,
        stop_tree=ops.stop_tree,
        run_task_argv=lambda bead, wt, slot, out, code: (
            [*childenv.script_argv((code or here) / "tl.py", env), "run-task", bead, "--loop", "--worktree", wt, "--outcome-file", out]
            + (["--slot", slot] if slot else [])
        ),
        landed_on_base=lambda wt, bead: landed_on_base(repo, cfg, store, wt, bead, git),
        reload_note=lambda bead: ops.reload_note(cfg, bead),
        chores=lambda: ops.chores(repo, spawner, env, git, who),
        release_dead=lambda: ops.release_dead(repo, store, now(), git, who),
        ask_lines=lambda: ask_sweeps.orphan_lines(wasks.store(cfg)),
        storm=lambda: storm(repo, cfg, now, git=git),
        probe=lambda: make_probe(repo, env, git),
        roles=lambda: roles(repo, env, git),
        has_delegate=lambda: bool(delegate_route(repo, env, git)),
        event=functools.partial(trail.event, who),
        pid_alive=pidcheck.pid_alive,
        behind=lambda v: catalog.releases_behind(v, ident.claude_dir(env)),
        version=here.parents[1].name,
        code_dir=str(here),
        session_actor=session_actor,
        actor=lambda: who.actor,
        exec_into=lambda d, argv, handover: ops.exec_into(repo, d, argv, handover, env, who, start_cwd),
        take_handover=lambda: env.get(EnvVar.TL_LOOP_STATE),
        host=lambda: JsonStore(cfg.host(), HostResources).need(),
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
            who=who,
        ),
        free_bytes=lambda: free_bytes(cfg),
        available_mb=lambda: available_mb(spawner),
    )
