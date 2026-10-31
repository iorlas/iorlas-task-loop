"""A terminal-independent loop, using the loop's existing liveness, lock, logs and stop command."""
import contextlib
import time
from collections import deque
from collections.abc import Callable, Generator
from pathlib import Path

from taskloop.adapters import factory as platform_factory
from taskloop.adapters.ident import plugin_version
from taskloop.app.loop.files import LoopFiles
from taskloop.contracts.loop import LoopState
from taskloop.contracts.ports import Spawner


def version() -> str:
    return plugin_version() or "unknown"


def recorded_pid(files: LoopFiles) -> int:
    try:
        return int((files.runs() / "loop.pid").read_text().strip())
    except (OSError, ValueError):
        return 0


def log_path(files: LoopFiles, state: LoopState | None = None) -> Path:
    if state and state.pid != recorded_pid(files) and state.log:
        return Path(state.log)
    return files.runs() / "factory.log"


def start(files: LoopFiles, repo: str, version: str, argv: list[str], spawner: Spawner,
          sleep: Callable[[float], None] = time.sleep) -> tuple[list[LoopState], bool]:
    """Serialize launch and record startup under the loop's lock before the child publishes its own state."""
    with files.lock():
        states = files.live()
        if states:
            return states, True
        with open(log_path(files), "ab") as out:
            # Spawner.start uses start_new_session=True (setsid) and DEVNULL stdin:
            # closing the launcher's terminal cannot hang up this session.
            child = spawner.start(argv, cwd=repo, stdin="null", out=out, extra={"PYTHONUNBUFFERED": "1"})
        (files.runs() / "loop.pid").write_text(str(child.pid) + "\n")
        files.write(LoopState(pid=child.pid, started=files.now(), t=files.now(), repo=repo, version=version, code_dir="", actor=""))
    # The child takes this same lock when publishing its first state, so wait outside it.
    for _ in range(100):
        if child.poll() is not None:
            raise RuntimeError(f"loop exited {child.poll()}; see {log_path(files)}")
        state = files.read(child.pid)
        if state and state.actor:
            keep_awake = platform_factory.caffeinate_argv(child.pid)
            if keep_awake:
                with contextlib.suppress(FileNotFoundError):
                    spawner.start(keep_awake, stdin="null", out="null")
            return [state], False
        sleep(0.1)
    raise RuntimeError(f"loop pid {child.pid} has not published state; see {log_path(files)}")


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
