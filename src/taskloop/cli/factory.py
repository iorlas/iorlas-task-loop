"""`tl factory`: start, inspect, stop and tail a repo's detached factory."""
import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from taskloop.app.artifacts import server
from taskloop.app.launch import dash, factory, loop, repos
from taskloop.app.loop.exits import last_by_lane
from taskloop.app.loop.files import LoopFiles
from taskloop.app.wire import real
from taskloop.contracts.artifact import ArtifactSlot
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
from taskloop.contracts.loop import LoopState
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.procport import Spawner
from taskloop.contracts.slots import SlotGitError


def facts(files: LoopFiles, states: list[LoopState], repo: str, version: str) -> None:
    print("REPO " + repo)
    if not states:
        print("not running")
        print("VERSION " + version)
        print("LOG " + str(factory.log_path(files)))
    for st in states:
        print(f"PID {st.pid}\nVERSION {st.version}\nLOG {factory.log_path(files, st)}")
        print("BEAD " + (st.bead or "-"))


def _wanted(repo: str, env: Env) -> int:
    try:
        return max(1, loop.profile_of(repo, real.git(env)).slots.count)
    except SystemExit as error:
        raise RuntimeError("cannot read repo profile") from error
    except SlotGitError as error:
        raise RuntimeError(f"cannot read repo profile: {error}") from error


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _stop(a: argparse.Namespace, files: LoopFiles, who: Identity) -> int:
    stopped = files.request_stop(a.now, who.actor)
    if not stopped:
        print("not running")
        return 1
    for st in stopped:
        print(f"STOP {'NOW' if a.now else 'after the current bead'}: loop pid {st.pid}")
    return 0


def _logs(a: argparse.Namespace, files: LoopFiles, states: list[LoopState]) -> int:
    state = factory.lane_states(files, states).get(a.lane)
    if state is None:
        raise RuntimeError(f"no live lane {a.lane}")
    for line in factory.lines(factory.log_path(files, state), a.n, a.follow):
        print(line, end="", flush=True)
    return 0


def run(a: argparse.Namespace, env: Env, spawner: Spawner, who: Identity, here: Path) -> int:
    repo = repos.repo_root(a.repo)
    files = loop.files_of(repo, who.config)
    version = factory.version()
    try:
        if a.op == "start":
            lanes = a.lanes if a.lanes is not None else _wanted(repo, env)
            argv = [sys.executable, str(here / "tl.py"), "loop", "--repo", repo, "--wait-drained"]
            states, added = factory.start(files, repo, version, argv, spawner, lanes=lanes)
            print(f"started {added} more lane(s)" if added else f"already running ({len(states)} lanes)")
            facts(files, states, repo, version)
            return dash.run("ensure", env, spawner)
        if a.op == "stop":
            return _stop(a, files, who)
        states = files.live()
        if a.op == "logs":
            return _logs(a, files, states)
        facts(files, list(factory.lane_states(files, states).values()), repo, version)
        try:
            wanted = str(_wanted(repo, env))
        except RuntimeError:
            wanted = "?"  # status must answer even when the profile cannot be read
        print(f"LANES running={len(states)} wanted={wanted}")
        for rec in last_by_lane(files.cfg.loop_runs(files.key)):
            print(f"LANE {rec.get('lane', rec['pid'])} LAST EXIT pid={rec['pid']} time={rec.get('t')} "
                  f"reason={rec['reason']} {rec.get('detail', '')}")
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
