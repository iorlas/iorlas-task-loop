"""`tl hooks install`: write the git hooks tl owns into its hooks dir (<config>/githooks/). Every subprocess tl starts gets that dir as
core.hooksPath. That is a default, not a lock: `git -c core.hooksPath=...` and --no-verify still beat it, and a git run outside tl
does not see it unless the owner sets core.hooksPath to the dir."""
import argparse
from collections.abc import Callable
from pathlib import Path

from taskloop.app.wire.hook import write_hooks
from taskloop.contracts.env import Env


def cmd_hooks(a: argparse.Namespace, env: Env, plugin_root: Path, out: Callable[[str], None] = print) -> int:
    written = write_hooks(plugin_root, env)
    if not written:
        out("tl: could not write the git hooks")
        return 1
    for f in written:
        out(f"installed {f}")
    return 0


def add_parser(sp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sp.add_parser("hooks", help="install the git hooks tl owns (pre-push: asks tl green per pushed tip)")
    p.add_argument("op", choices=["install"])
