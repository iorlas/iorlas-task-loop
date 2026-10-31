"""`tl factory`: start, inspect, stop and tail a repo's detached factory."""
import argparse
import sys
from pathlib import Path

from taskloop.app.launch import dash, factory, loop, repos
from taskloop.app.loop.files import LoopFiles
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.loop import LoopState
from taskloop.contracts.ports import Spawner


def facts(files: LoopFiles, states: list[LoopState], repo: str, version: str) -> None:
    print("REPO " + repo)
    if not states:
        print("not running")
        print("VERSION " + version)
        print("LOG " + str(factory.log_path(files)))
    for st in states:
        print(f"PID {st.pid}\nVERSION {st.version}\nLOG {factory.log_path(files, st)}")
        if st.bead:
            print("BEAD " + st.bead)


def _stop(a: argparse.Namespace, files: LoopFiles, who: Identity) -> int:
    stopped = files.request_stop(a.now, who.actor)
    if not stopped:
        print("not running")
        return 1
    for st in stopped:
        print(f"STOP {'NOW' if a.now else 'after the current bead'}: loop pid {st.pid}")
    return 0


def run(a: argparse.Namespace, env: Env, spawner: Spawner, who: Identity, here: Path) -> int:
    repo = repos.repo_root(a.repo)
    files = loop.files_of(repo, who.config)
    version = factory.version()
    try:
        if a.op == "start":
            argv = [sys.executable, str(here / "tl.py"), "loop", "--repo", repo, "--wait-drained"]
            states, already = factory.start(files, repo, version, argv, spawner)
            print("already running" if already else "started")
            facts(files, states, repo, version)
            return dash.run("ensure", env, spawner)
        if a.op == "stop":
            return _stop(a, files, who)
        states = files.live()
        if a.op == "logs":
            path = factory.log_path(files, states[0] if states else None)
            for line in factory.lines(path, a.n, a.follow):
                print(line, end="", flush=True)
            return 0
        facts(files, states, repo, version)
        dash.url(env)
        return 0 if states else 1
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
        if op == "stop":
            command.add_argument("--now", action="store_true")
        if op == "logs":
            command.add_argument("-n", type=int, default=50)
            command.add_argument("-f", dest="follow", action="store_true")
