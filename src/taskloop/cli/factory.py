"""`tl factory`: start, inspect, stop and tail a repo's detached factory."""
import argparse
import sys
from collections.abc import Callable, Generator
from pathlib import Path

from tlartifacts import server
from tlkernel.artifact import ArtifactSlot
from tlkernel.env import Env
from tlkernel.identity import Identity
from tlkernel.paths import ConfigDir
from tlkernel.procport import Spawner

from taskloop.app.launch import dash, loop, repos
from taskloop.app.launch import factory as binding
from taskloop.app.loop import factory_verbs
from taskloop.app.loop.files import LoopFiles
from taskloop.app.parts import STAGE_PARTS
from taskloop.app.wire import real


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _print(result: tuple[Generator[str], int], *, end: str = "\n", flush: bool = False) -> int:
    rows, code = result
    for row in rows:
        print(row, end=end, flush=flush)
    return code


def _start(a: argparse.Namespace, files: LoopFiles, repo: str, version: str,
           env: Env, spawner: Spawner, here: Path) -> int:
    argv = [sys.executable, str(here / "tl.py"), "loop", "--repo", repo, "--wait-drained"]
    for row in factory_verbs.start_lines(files, repo, version, argv, spawner, a.loops,
                                         lambda: loop.profile_of(repo, real.git(env)), binding.caffeinate_argv):
        print(row)
    return dash.run("ensure", env, spawner, {p.name: p.version for p in STAGE_PARTS})


def run(a: argparse.Namespace, env: Env, spawner: Spawner, who: Identity, here: Path) -> int:
    repo = repos.repo_root(a.repo)
    files = loop.files_of(repo, who.config)
    version = binding.version()
    try:
        operations = {
            "start": lambda: _start(a, files, repo, version, env, spawner, here),
            "stop": lambda: _print(factory_verbs.stop_lines(files, a.now, who.actor)),
            "logs": lambda: _print(factory_verbs.log_lines(files, files.live(), a.loop, a.n, a.follow), end="", flush=True),
            "status": lambda: _print(factory_verbs.status_lines(
                files, files.live(), repo, version, lambda: loop.profile_of(repo, real.git(env)), lambda: dash.url(env))),
        }
        return operations[a.op]()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"tl factory: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


def add_parser(sp: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = sp.add_parser("factory", help="run the factory independently of this terminal")
    operations = parser.add_subparsers(dest="op", required=True)
    for op in ("start", "status", "stop", "logs"):
        command = operations.add_parser(op)
        command.add_argument("--repo", metavar="DIR")
        if op == "start":
            command.add_argument("--loops", type=_positive, metavar="N")
        if op == "stop":
            command.add_argument("--now", action="store_true")
        if op == "logs":
            command.add_argument("--loop", type=_positive, default=1, metavar="K")
            command.add_argument("-n", type=int, default=50)
            command.add_argument("-f", dest="follow", action="store_true")


def serve_artifacts(a: argparse.Namespace, cfg: ConfigDir, now: Callable[[], float]) -> int:
    """`tl artifact-server`: the artifact_add stdio MCP server a worker's harness starts for one call. Internal, not a session command:
    the binding comes from argv (the factory writes it, the model cannot) and stdout carries only protocol lines."""
    slot = ArtifactSlot(repo=a.repo, bead=a.bead, run=a.run, stage=a.stage, attempt=a.attempt)
    return server.serve(sys.stdin, sys.stdout, cfg.artifact_store(), slot, Path(a.cwd), now)
