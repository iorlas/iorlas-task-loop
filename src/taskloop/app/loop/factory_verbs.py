"""Factory lane targets, stop results, log selection and status facts for the loop node."""
import contextlib
import time
from collections import deque
from collections.abc import Callable, Generator
from pathlib import Path

from tlkernel.config import RepoProfile
from tlkernel.loop import LoopState
from tlkernel.procport import Child, Spawner
from tlkernel.slots import SlotGitError

from taskloop.app.loop.files import LoopFiles


def wanted(profile: Callable[[], RepoProfile]) -> int:
    try:
        return max(1, profile().slots.count)
    except SystemExit as error:
        raise RuntimeError("cannot read repo profile") from error
    except SlotGitError as error:
        raise RuntimeError(f"cannot read repo profile: {error}") from error


def status_wanted(profile: Callable[[], RepoProfile]) -> str:
    """Status must answer even when the profile cannot be read."""
    try:
        return str(wanted(profile))
    except RuntimeError:
        return "?"


def stop(files: LoopFiles, now: bool, actor: str) -> list[LoopState] | None:
    return files.request_stop(now, actor) or None


def logs(files: LoopFiles, states: list[LoopState], lane: int) -> tuple[LoopState, Path]:
    state = lane_states(files, states).get(lane)
    if state is None:
        raise RuntimeError(f"no live lane {lane}")
    return state, log_path(files, state)


def facts(files: LoopFiles, states: list[LoopState], repo: str, version: str) -> list[str]:
    rows = ["REPO " + repo]
    if not states:
        rows.extend(("not running", "VERSION " + version, "LOG " + str(log_path(files))))
    for st in states:
        rows.append(f"PID {st.pid}\nVERSION {st.version}\nLOG {log_path(files, st)}")
        rows.append("BEAD " + (st.bead or "-"))
    return rows


def status_facts(files: LoopFiles, states: list[LoopState], repo: str, version: str) -> list[str]:
    return facts(files, list(lane_states(files, states).values()), repo, version)


def no_keep_awake(pid: int) -> list[str]:
    """The default keep-awake: none (the launcher passes the platform one)."""
    return []


def recorded_pid(files: LoopFiles) -> int:
    try:
        return int((files.runs() / "loop.pid").read_text().strip())
    except (OSError, ValueError):
        return 0


def log_path(files: LoopFiles, state: LoopState | None = None) -> Path:
    if state and state.log:
        return Path(state.log)
    if state and (path := files.runs() / f"factory-{state.pid}.log").exists():
        return path
    return files.runs() / "factory.log"


def lane_states(files: LoopFiles, states: list[LoopState]) -> dict[int, LoopState]:
    """The launcher keeps numbered links even when the child publishes its own log."""
    numbered: dict[int, LoopState] = {}
    by_pid = {st.pid: st for st in states}
    for state in states:
        stem = Path(state.log).stem
        if stem.startswith("factory-lane-") and (suffix := stem.removeprefix("factory-lane-")).isdigit():
            lane = int(suffix)
            if lane > 0:
                numbered[lane] = by_pid.pop(state.pid)
    for path in sorted(files.runs().glob("factory-lane-*.log")):
        try:
            lane = int(path.stem.removeprefix("factory-lane-"))
            pid = int(path.readlink().stem.removeprefix("factory-"))
        except (OSError, ValueError):
            continue
        if lane > 0 and pid in by_pid:
            numbered[lane] = by_pid.pop(pid)
    for state in by_pid.values():
        lane = next(k for k in range(1, len(states) + 1) if k not in numbered)
        numbered[lane] = state
    return dict(sorted(numbered.items()))


def _spawn(files: LoopFiles, repo: str, version: str, argv: list[str], spawner: Spawner, lane: int) -> tuple[Child, Path]:
    path = files.runs() / f"factory-lane-{lane}.log"
    path.unlink(missing_ok=True)
    with path.open("ab") as out:
        # Spawner.start detaches the session and disconnects its terminal input.
        child = spawner.start(argv, cwd=repo, stdin="null", out=out, extra={"PYTHONUNBUFFERED": "1"})
    log = files.runs() / f"factory-{child.pid}.log"
    path.replace(log)
    path.symlink_to(log.name)
    state = files.read(child.pid)
    if state is None or not state.actor:
        files.write(LoopState(pid=child.pid, started=files.now(), t=files.now(), repo=repo, version=version,
                              code_dir="", actor="", log=str(log)))
    return child, log


def _wait(files: LoopFiles, children: list[tuple[Child, Path]], sleep: Callable[[float], None]) -> list[LoopState]:
    ready: dict[int, LoopState] = {}
    for _ in range(100):
        for child, path in children:
            code = child.poll()
            if code is not None:
                state = files.read(child.pid)
                if state is not None:
                    files.record_dead(state, "signal" if code < 0 else "clean" if code == 0 else "crash",
                                      f"launcher observed exit {code}")
                raise RuntimeError(f"loop exited {code}; see {path}")
            if child.pid in ready:
                continue
            with files.lock():
                state = files.read(child.pid)
                if state and state.actor:
                    if not state.log:
                        state = state.replace(log=str(path))
                        files.write(state)
                    ready[child.pid] = state
        if len(ready) == len(children):
            return list(ready.values())
        sleep(0.1)
    child, path = next((child, path) for child, path in children if child.pid not in ready)
    raise RuntimeError(f"loop pid {child.pid} has not published state; see {path}")


def start(files: LoopFiles, repo: str, version: str, argv: list[str], spawner: Spawner,
          sleep: Callable[[float], None] = time.sleep, *, lanes: int = 1,
          caffeinate_argv: Callable[[int], list[str]] = no_keep_awake) -> tuple[list[LoopState], int]:
    """Top up under the loop lock; return all lanes and the number newly launched."""
    if lanes < 1:
        raise ValueError("lanes must be at least 1")
    children: list[tuple[Child, Path]] = []
    with files.lock():
        states = files.live()
        numbered = lane_states(files, states)
        for _ in range(max(0, lanes - len(states))):
            lane = next(k for k in range(1, lanes + 1) if k not in numbered)
            child, path = _spawn(files, repo, version, argv, spawner, lane)
            children.append((child, path))
            numbered[lane] = LoopState(pid=child.pid, started=0, t=0, repo=repo, version=version, code_dir="", actor="")
        if numbered:
            (files.runs() / "loop.pid").write_text(str(numbered[min(numbered)].pid) + "\n")
    # The child uses the same lock to publish; wait outside the launch lock.
    if children:
        states.extend(_wait(files, children, sleep))
        for child, _ in children:
            keep_awake = caffeinate_argv(child.pid)
            if keep_awake:
                with contextlib.suppress(FileNotFoundError):
                    spawner.start(keep_awake, stdin="null", out="null")
    return list(lane_states(files, states).values()), len(children)


def lines(path: Path, n: int, follow: bool = False, sleep: Callable[[float], None] = time.sleep) -> Generator[str]:
    """Tail with bounded memory, then keep reading the same open log when following."""
    if n < 0:
        raise ValueError("line count must be nonnegative")
    with path.open(encoding="utf-8", errors="replace") as stream:
        yield from deque(stream, maxlen=n)
        while follow:
            line = stream.readline()
            if line:
                yield line
            else:
                sleep(0.2)
