"""Starting a loop and looking at the others: its identity, the installs on the machine, what runs on it."""
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path

from taskloop.adapters import ident
from taskloop.app.doctor import profiles
from taskloop.app.launch.loop import HERE, live_loops
from taskloop.app.loop.loop import parse_handover
from taskloop.app.loop.versions import Installs
from taskloop.app.release import catalog, pins
from taskloop.app.slots import engine_lock
from taskloop.app.track import trail
from taskloop.app.wire import slots as wslots
from taskloop.contracts import paths
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.gitport import Git
from taskloop.contracts.identity import Identity
from taskloop.contracts.rowstores import ReposStore


def installs(cfg: paths.ConfigDir, env: Env, here: Path = HERE, now: Callable[[], float] = trail.now) -> Installs:
    """The installs of task-loop on this machine."""
    return Installs(cfg, here.parents[1], lambda: catalog.installed_version("task-loop", ident.claude_dir(env)),
                    lambda: pins.read_pin(env).task_loop or "",
                    now=now)


def other_red_rows(git: Git, repo: str, cfg: paths.ConfigDir) -> list[str]:
    """The red rows of the other registered repos' bad profiles (`tl loop status` shows them; nothing else changes)."""
    return profiles.red_rows(git, profiles.registered(ReposStore(cfg)), but=repo)


def begin_loop(repo: str, env: Env) -> tuple[str, str, Identity]:
    """Make this process the loop of `repo`: its working directory, its own actor. -> (the start directory, the session's actor, the
    identity the loop and its children act as)."""
    start_cwd = os.getcwd()
    os.chdir(repo)  # every tl helper and bd call works on the current directory's repo
    inherited, _ = parse_handover(
        env.get(EnvVar.TL_LOOP_STATE)
    )  # set when this process is the same loop, exec'd into a newer install
    # an actor of its own, never the session's: bd lets an actor re-claim its own bead, so two loops (or a loop and a hand run)
    # started from one session would both win one claim. run-task re-claims as this actor (one for both).
    own = Env({k: v for k, v in env.vars.items() if k != EnvVar.TASK_LOOP_ACTOR.value})
    if not ident.identity(own).session:  # without a Claude session the actor would be per folder: two loops would share it
        own = own.with_(EnvVar.TASK_LOOP_SESSION, "loop-" + uuid.uuid4().hex[:12])
    session = ident.identity(own)
    loop_actor = (inherited.actor if inherited else "") or f"{session.actor}-{uuid.uuid4().hex[:6]}"
    return start_cwd, session.actor, Identity(actor=loop_actor, home=session.home, session=session.session)


def live_work(git: Git, who: Identity) -> list[tuple[str, str]]:
    """What runs on this machine: ("loop"|"run", text) for every live loop and every busy engine lock of the registered repos."""
    repos = [r for r in ReposStore(who.config).known() if os.path.isdir(r)]
    out: list[tuple[str, str]] = []
    for r in repos:
        for st in live_loops(r, who.config):
            out.append(("loop", "loop pid {} on {}{}".format(st.pid, r, (" running " + st.bead) if st.bead else "")))
        for wt in [r, *wslots.worktrees(r, git, who, slots=None if shutil.which("bd") else [])]:  # slot dirs need bd
            busy = engine_lock.engine_busy(who.config, wt)
            if busy:
                out.append(("run", f"run in {wt}: {busy}"))
    return out
