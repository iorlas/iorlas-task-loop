"""Bind the loop node's world-facing verbs to real ports and stages; launch/loop.py binds the repo into the LoopEnv."""
import platform
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO

from tlkernel import bdbackup, factorybackup, paths
from tlkernel.beadsport import Beads
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.landed import landed_by
from tlkernel.procport import Child, Hold, Spawner
from tlkernel.slots import git_probe

from taskloop.adapters import beadtools, childenv, ident, ram
from taskloop.adapters import storm as storm_file
from taskloop.adapters.bd import BdStore
from taskloop.adapters.repourl import repo_url
from taskloop.app.asks import admission
from taskloop.app.doctor import disk
from taskloop.app.loop import stages
from taskloop.app.loop.env import ReloadNote, Storm
from taskloop.app.reconcile import leases
from taskloop.app.release import reexec
from taskloop.app.report import reflect
from taskloop.app.run.running import running
from taskloop.app.slots import config as wslots_config
from taskloop.app.slots import engine_lock
from taskloop.app.track import console, trail, verbs
from taskloop.app.wire import asks as wasks
from taskloop.app.wire import lanes as wlanes
from taskloop.app.wire import slots as wslots
from taskloop.domain import outcome as oc

STOP_GRACE_S = stages.STOP_GRACE_S


def reload_note(cfg: paths.ConfigDir, bead: BeadId) -> ReloadNote | None:
    return stages.reload_note(lambda: reexec.read_reexec(cfg, bead), lambda: reexec.drop_reexec(cfg, bead))


def fetch(repo: str, git: Git) -> None:
    stages.fetch(repo, git)


def release_dead(repo: str, store: Beads, now: float, git: Git, who: Identity) -> list[str]:
    return leases.release_dead(repo, store, running(repo, git, who, store), ident.hostname(), now)


def chores(repo: str, spawner: Spawner, env: Env, git: Git, who: Identity, store: BdStore | None = None) -> None:
    stages.chores(
        lambda: wlanes.chore(console.say, spawner, env),
        lambda: wslots_config.load_cfg(repo, git),
        lambda cfg: wasks.sweep_asks(who, who.config, console.say, cfg, repo),
        lambda cfg: wasks.wake_prs(who, who.config, spawner, cfg, repo),
        lambda: reflect.maybe_run(spawner, env, who.config),
        lambda: factorybackup.backup(who.config, trail.now()),
        lambda: disk.sample_volume(who.config, trail.now(), console.say),
        store,
        lambda store: bdbackup.nightly(who.config, wslots.repo_key(repo), lambda argv: _bd(store, argv), trail.now()),
        console.say,
    )


def _bd(store: BdStore, argv: list[str]) -> tuple[int, str, str]:
    r = store.passthrough(argv)
    return r.code, r.out, r.err


def claim(repo: str, store: Beads, bead: BeadId, wt: str, slot: str, git: Git, who: Identity,
          now: Callable[[], float] = trail.now) -> tuple[bool, str]:
    return stages.claim(
        lambda: admission.admit(bead, repo, git, who, store, now(), running_now=running),
        lambda: verbs.claim(who, bead, store, git, wt, slot),
    )


def spawn(spawner: Spawner, cmd: list[str], log: IO[bytes], extra: Mapping[str, str]) -> tuple[Child, Hold]:
    """run-task as a child in its own process group: Ctrl-C to the loop reaches it only as the loop's SIGTERM.
    -> (the child, the hold of its spawn): the caller replays the hold first inside the try that stops the child."""
    return spawner.start_held(cmd, out=log, extra=extra)


def stop_now(child: Child) -> None:
    stages.stop_now(child)


def stop_tree(child: Child) -> None:
    stages.stop_tree(child)


def exec_into(repo: str, d: Path, argv: list[str], handover: str, env: Env, who: Identity, start_cwd: str = "") -> None:
    stages.exec_into(repo, start_cwd, lambda: [*childenv.script_argv(d / "skills" / "task-loop" / "tl.py", env), *argv],
                     lambda: childenv.exec_env(env, {EnvVar.TL_LOOP_STATE: handover, EnvVar.TASK_LOOP_SESSION: who.session}))


def loop_lock(cfg: paths.ConfigDir, wt: str, slot: str, slot_bead: str | None, bead: str) -> None:
    stages.loop_lock(wt, slot, slot_bead, bead, lambda wt, slot, slot_bead, bead: engine_lock.loop_lock(
        cfg, wt, slot, slot_bead, bead=bead))


def available_mb(spawner: Spawner) -> int | None:
    return stages.available_mb(platform.system, spawner, ram.available_mb)


def landed_on_base(repo: str, cfg: paths.ConfigDir, store: Beads, wt: str, bead_id: BeadId, git: Git) -> bool:
    """True when the bead's landed record names a sha that is on the base. LEGACY, only for a bead with no record (landed before
    0.23.179): its land commit (titled `... (<id>)`) is the tip of its branch and already on the base; this can go with them."""
    return git_probe(lambda: _landed_on_base(repo, cfg, store, wt, bead_id, git), False)


def _landed_on_base(repo: str, cfg: paths.ConfigDir, store: Beads, wt: str, bead_id: BeadId, git: Git) -> bool:
    return stages.landed_on_base(repo, wt, bead_id, git, lambda: wslots_config.load_cfg(repo, git).base,
                                 lambda: landed_by(store)(bead_id), lambda: beadtools.peek(store, bead_id))


def storm(repo: str, cfg: paths.ConfigDir, now: Callable[[], float] = trail.now, *, git: Git) -> Storm | None:
    return stages.storm(
        lambda: storm_file.storm_path(cfg.root, repo_url(git, repo)),
        lambda path: storm_file.read_storm(path, now(), oc.KNOBS["storm_window_s"]),
        oc.KNOBS["storm_window_s"],
    )
