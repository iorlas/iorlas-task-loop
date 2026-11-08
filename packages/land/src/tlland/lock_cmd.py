"""Run a command while holding the repo's land lock, shared with the engine."""
import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from tlkernel.slots import MissingRemote


def cmd_land_lock(a: argparse.Namespace, remote_url: Callable[[str], str],
                  run_locked: Callable[[list[str], str, float | None, str], int]) -> int:
    cmd = list(a.cmd_args)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("land-lock: no command (usage: tl.py land-lock [--repo DIR] -- CMD...)", file=sys.stderr)
        return 2
    repo = str(Path(a.repo).resolve())
    try:
        origin = remote_url(repo)
    except MissingRemote:
        origin = ""
    return run_locked(cmd, repo, a.wait_min, origin)
