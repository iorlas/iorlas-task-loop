"""Factory loop targets, stop results, log selection and status facts for the loop node."""
import contextlib
import time
from collections import deque
from collections.abc import Callable, Generator
from pathlib import Path

from tlkernel.config import RepoProfile
from tlkernel.loop import LoopState
from tlkernel.procport import Child, Spawner
from tlkernel.slots import SlotGitError

from taskloop.app.loop.exits import last_by_loop
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


def logs(files: LoopFiles, states: list[LoopState], loop_no: int) -> tuple[LoopState, Path]:
    state = loop_states(files, states).get(loop_no)
    if state is None:
        raise RuntimeError(f"no live loop {loop_no}")
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
    return facts(files, list(loop_states(files, states).values()), repo, version)


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


def loop_states(files: LoopFiles, states: list[LoopState]) -> dict[int, LoopState]:
    """The launcher keeps numbered links even when the child publishes its own log."""
    numbered: dict[int, LoopState] = {}
    by_pid = {st.pid: st for st in states}
    for state in states:
        stem = Path(state.log).stem
        if stem.startswith("factory-loop-") and (suffix := stem.removeprefix("factory-loop-")).isdigit():
            loop_no = int(suffix)
            if loop_no > 0:
                numbered[loop_no] = by_pid.pop(state.pid)
    for path in sorted(files.runs().glob("factory-loop-*.log")):
        try:
            loop_no = int(path.stem.removeprefix("factory-loop-"))
            pid = int(path.readlink().stem.removeprefix("factory-"))
        except (OSError, ValueError):
            continue
        if loop_no > 0 and pid in by_pid:
            numbered[loop_no] = by_pid.pop(pid)
    for state in by_pid.values():
        loop_no = next(k for k in range(1, len(states) + 1) if k not in numbered)
        numbered[loop_no] = state
    return dict(sorted(numbered.items()))


def _spawn(files: LoopFiles, repo: str, version: str, argv: list[str], spawner: Spawner, loop_no: int) -> tuple[Child, Path]:
    path = files.runs() / f"factory-loop-{loop_no}.log"
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
          sleep: Callable[[float], None] = time.sleep, *, loops: int = 1,
          caffeinate_argv: Callable[[int], list[str]] = no_keep_awake) -> tuple[list[LoopState], int]:
    """Top up under the loop lock; return all loops and the number newly launched."""
    if loops < 1:
        raise ValueError("loops must be at least 1")
    children: list[tuple[Child, Path]] = []
    with files.lock():
        states = files.live()
        numbered = loop_states(files, states)
        for _ in range(max(0, loops - len(states))):
            loop_no = next(k for k in range(1, loops + 1) if k not in numbered)
            child, path = _spawn(files, repo, version, argv, spawner, loop_no)
            children.append((child, path))
            numbered[loop_no] = LoopState(pid=child.pid, started=0, t=0, repo=repo, version=version, code_dir="", actor="")
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
    return list(loop_states(files, states).values()), len(children)


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


def stop_lines(files: LoopFiles, now: bool, actor: str) -> tuple[Generator[str], int]:
    stopped = stop(files, now, actor)
    if stopped is None:
        return (row for row in ["not running"]), 1
    return (f"STOP {'NOW' if now else 'after the current bead'}: loop pid {st.pid}" for st in stopped), 0


def status_lines(files: LoopFiles, states: list[LoopState], repo: str, version: str,
                 profile: Callable[[], RepoProfile], dash_url: Callable[[], object]) -> tuple[Generator[str], int]:
    def rows() -> Generator[str]:
        yield from status_facts(files, states, repo, version)
        yield f"LOOPS running={len(states)} wanted={status_wanted(profile)}"
        for rec in last_by_loop(files.cfg.loop_runs(files.key)):
            yield (f"LOOP {rec.get('loop', rec['pid'])} LAST EXIT pid={rec['pid']} time={rec.get('t')} "
                   f"reason={rec['reason']} {rec.get('detail', '')}")
        dash_url()
    return rows(), 0 if states else 1


def log_lines(files: LoopFiles, states: list[LoopState], loop_no: int, n: int,
              follow: bool) -> tuple[Generator[str], int]:
    _, path = logs(files, states, loop_no)
    return lines(path, n, follow), 0


def start_lines(files: LoopFiles, repo: str, version: str, argv: list[str], spawner: Spawner,
                loops: int | None, profile: Callable[[], RepoProfile],
                caffeinate_argv: Callable[[int], list[str]]) -> Generator[str]:
    target = loops if loops is not None else wanted(profile)
    states, added = start(files, repo, version, argv, spawner, loops=target, caffeinate_argv=caffeinate_argv)
    yield f"started {added} more loop(s)" if added else f"already running ({len(states)} loops)"
    yield from facts(files, states, repo, version)
