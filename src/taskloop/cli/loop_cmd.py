"""The verbs `tl next`, `tl loop [status]`, `tl stop` and `tl cutover check`: find the repo, build its LoopEnv (app/launch/loop.py),
hand it to the printing and running verbs of cli/loop.py. `here` is the install this run executes from, `now` the clock."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.procport import Spawner

from taskloop.app.launch import loop as wloop
from taskloop.app.launch import loop_start as wstart
from taskloop.app.launch import repos
from taskloop.app.loop import render
from taskloop.app.track import trail
from taskloop.cli import loop as cli


def cmd_next(
    a: Any, env: Env, spawner: Spawner, git: Git, who: Identity, here: Path = wloop.HERE, now: Callable[[], float] = trail.now
) -> int:
    repo = repos.repo_root(a.repo)
    return cli.cmd_next(wloop.build(repo, here=here, now=now, env=env, spawner=spawner, git=git, who=who), a)


def cmd_stop(
    a: Any, env: Env, spawner: Spawner, git: Git, who: Identity, here: Path = wloop.HERE, now: Callable[[], float] = trail.now
) -> int:
    repo = repos.repo_root(a.repo)
    loop_env = wloop.build(repo, here=here, now=now, env=env, spawner=spawner, git=git, who=who)
    return cli.cmd_stop(loop_env, wloop.files_of(repo, who.config, now), a)


def cmd_loop(
    a: Any, env: Env, spawner: Spawner, git: Git, who: Identity, here: Path = wloop.HERE, now: Callable[[], float] = trail.now
) -> int:
    return cli.emit(
        wstart.command(
            a.repo,
            a.op,
            a.last,
            env,
            spawner,
            git,
            who,
            here,
            now,
            lambda loop_env, files, installs: cli.cmd_loop(loop_env, files, installs, a),
        )
    )


def cmd_cutover(a: Any, git: Git, who: Identity) -> int:
    return cli.emit(render.cutover_lines(wstart.live_work(git, who), a.json))
