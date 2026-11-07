"""`tl factory`: start, inspect, stop and tail a repo's detached factory."""
import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from tlkernel.artifact import ArtifactSlot
from tlkernel.env import Env
from tlkernel.identity import Identity
from tlkernel.loop import LoopState
from tlkernel.paths import ConfigDir
from tlkernel.procport import Spawner

from taskloop.app.artifacts import server
from taskloop.app.launch import dash, loop, repos
from taskloop.app.launch import factory as binding
from taskloop.app.loop import factory_verbs
from taskloop.app.loop.exits import last_by_lane
from taskloop.app.loop.files import LoopFiles
from taskloop.app.wire import real


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _stop(a: argparse.Namespace, files: LoopFiles, who: Identity) -> int:
    stopped = factory_verbs.stop(files, a.now, who.actor)
    if stopped is None:
        print("not running")
        return 1
    for st in stopped:
        print(f"STOP {'NOW' if a.now else 'after the current bead'}: loop pid {st.pid}")
    return 0


def _status(files: LoopFiles, states: list[LoopState], repo: str, version: str, env: Env) -> int:
    for row in factory_verbs.status_facts(files, states, repo, version):
        print(row)
    wanted = factory_verbs.status_wanted(lambda: loop.profile_of(repo, real.git(env)))
    print(f"LANES running={len(states)} wanted={wanted}")
    for rec in last_by_lane(files.cfg.loop_runs(files.key)):
        print(f"LANE {rec.get('lane', rec['pid'])} LAST EXIT pid={rec['pid']} time={rec.get('t')} "
              f"reason={rec['reason']} {rec.get('detail', '')}")
    dash.url(env)
    return 0 if states else 1


def _logs(a: argparse.Namespace, files: LoopFiles, states: list[LoopState]) -> int:
    _, path = factory_verbs.logs(files, states, a.lane)
    for line in factory_verbs.lines(path, a.n, a.follow):
        print(line, end="", flush=True)
    return 0


def run(a: argparse.Namespace, env: Env, spawner: Spawner, who: Identity, here: Path) -> int:
    repo = repos.repo_root(a.repo)
    files = loop.files_of(repo, who.config)
    version = binding.version()
    try:
        if a.op == "start":
            lanes = a.lanes if a.lanes is not None else factory_verbs.wanted(lambda: loop.profile_of(repo, real.git(env)))
            argv = [sys.executable, str(here / "tl.py"), "loop", "--repo", repo, "--wait-drained"]
            states, added = factory_verbs.start(files, repo, version, argv, spawner, lanes=lanes,
                                              caffeinate_argv=binding.caffeinate_argv)
            print(f"started {added} more lane(s)" if added else f"already running ({len(states)} lanes)")
            for row in factory_verbs.facts(files, states, repo, version):
                print(row)
            return dash.run("ensure", env, spawner)
        if a.op == "stop":
            return _stop(a, files, who)
        states = files.live()
        if a.op == "logs":
            return _logs(a, files, states)
        return _status(files, states, repo, version, env)
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
            command.add_argument("--lanes", type=_positive, metavar="N")
        if op == "stop":
            command.add_argument("--now", action="store_true")
        if op == "logs":
            command.add_argument("--lane", type=_positive, default=1, metavar="K")
            command.add_argument("-n", type=int, default=50)
            command.add_argument("-f", dest="follow", action="store_true")


def serve_artifacts(a: argparse.Namespace, cfg: ConfigDir, now: Callable[[], float]) -> int:
    """`tl artifact-server`: the artifact_add stdio MCP server a worker's harness starts for one call. Internal, not a session command:
    the binding comes from argv (the factory writes it, the model cannot) and stdout carries only protocol lines."""
    slot = ArtifactSlot(repo=a.repo, bead=a.bead, run=a.run, stage=a.stage, attempt=a.attempt)
    return server.serve(sys.stdin, sys.stdout, cfg.artifact_store(), slot, Path(a.cwd), now)
