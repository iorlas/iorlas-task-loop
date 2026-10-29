"""The verbs `tl next`, `tl loop [status]`, `tl stop` and `tl cutover check`: find the repo, build its LoopEnv (app/launch/loop.py),
hand it to the printing and running verbs of cli/loop.py. `here` is the install this run executes from, `now` the clock."""
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from taskloop.app.doctor import profiles
from taskloop.app.launch import loop as wloop
from taskloop.app.launch import repos
from taskloop.app.track import trail
from taskloop.cli import loop as cli


def cmd_next(a: Any, here: Path = wloop.HERE, now: Callable[[], float] = trail.now) -> int:
    repo = repos.repo_root(a.repo)
    return cli.cmd_next(wloop.build(repo, here=here, now=now), a)


def cmd_stop(a: Any, here: Path = wloop.HERE, now: Callable[[], float] = trail.now) -> int:
    repo = repos.repo_root(a.repo)
    return cli.cmd_stop(wloop.build(repo, here=here, now=now), wloop.files_of(repo, now), a)


def cmd_loop(a: Any, here: Path = wloop.HERE, now: Callable[[], float] = trail.now) -> int:
    repo = repos.repo_root(a.repo)
    if profiles.red_row(repo):
        print(profiles.red_row(repo))
        return 1
    env = wloop.build(repo, here=here, now=now)
    files = wloop.files_of(repo, now)
    if a.op == "status":
        for row in wloop.other_red_rows(repo):
            print(row)  # another repo's bad profile: its red row here, nothing else changes
        return cli.cmd_status(env, files, wloop.installs(env.cfgdir, lambda: env.profile().loop, here, now), a)
    start_cwd, session = wloop.begin_loop(repo)
    env = wloop.build(repo, session_actor=session, here=here, now=now, start_cwd=start_cwd)
    return cli.cmd_loop(env, files, wloop.installs(env.cfgdir, lambda: env.profile().loop, here, now), a)


def cmd_cutover(a: Any) -> int:
    live = wloop.live_work()
    if a.json:
        print(json.dumps({"live": [{"kind": k, "what": w} for k, w in live]}))
    elif live:
        print("\n".join(f"LIVE {w}" for _, w in live))
    else:
        print("CLEAR: no live loop or run")
    return 1 if live else 0
