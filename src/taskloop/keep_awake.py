"""Keep-awake while `tl step rounds` runs (B11): one helper child that asks the OS not to idle-sleep and ends with rounds.

The helper's command by platform (`command`): macOS `caffeinate -i -w <rounds pid>`; Linux `systemd-inhibit ... tail
--pid=<rounds pid> -f /dev/null`; anything else none. Each also ends by itself when rounds exit (`-w`, `tail --pid`), so a
`kill -9` of rounds leaves no helper behind for long. Best effort: a missing tool, another platform or a failed start is
one `rounds keep_awake unavailable:<why>` log line and one stderr line, and the rounds run anyway; the factory never
checks that the inhibitor took effect.

The helper is spawned through the shelf (`Host.spawn`, real: `composition.keep_awake_spawn`, `stream_proc.popen_held`),
whose hold notes SIGINT and SIGTERM until `Helper.replay`: `awake` calls it first inside the `try` whose `finally` stops
the helper (`Helper.stop`, real: `stream_proc.stop_tree`), so a Ctrl-C during the spawn is replayed where the helper is
already stopped on the way out. The caller enters `awake` before the rounds' own SIGINT handler (`interrupts.installed`).
This module sends no signal and imports no process API.
"""

from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final

from taskloop.evidence_files import EvidenceError
from taskloop.round_log import stamped

WHO: Final = "taskloop"
TOOLS: Final = {"darwin": ("caffeinate",), "linux": ("systemd-inhibit", "tail")}  # by `sys.platform` (any `linux*`)


@dataclass(frozen=True)
class Helper:
    """A started helper: its pid, the shelf hold's `replay` (call once, first) and `stop` (stop its whole tree)."""

    pid: int
    replay: Callable[[], None]
    stop: Callable[[], object]


@dataclass(frozen=True)
class Host:
    """`platform` as `sys.platform`; `which` finds a tool on PATH (`shutil.which`); `spawn` starts the helper (OSError
    when it cannot)."""

    platform: str
    which: Callable[[str], str | None]
    spawn: Callable[[Sequence[str]], Helper]


@dataclass(frozen=True)
class Unavailable:
    word: str  # `platform`, `missing` or `start`: the log word after `unavailable:`
    detail: str  # for the person's stderr line only


def command(host: Host, pid: int, backlog: str) -> list[str] | Unavailable:
    """The helper's argv for this platform, each tool resolved on PATH; `Unavailable` when there is none."""
    tools = TOOLS.get("linux" if host.platform.startswith("linux") else host.platform)
    if tools is None:
        return Unavailable("platform", f"no keep-awake helper on {host.platform}")
    found = [host.which(tool) for tool in tools]
    paths = [path for path in found if path is not None]
    if len(paths) != len(tools):
        missing = [tool for tool, path in zip(tools, found, strict=True) if path is None]
        return Unavailable("missing", f"{', '.join(missing)} not on PATH")
    if len(paths) == 1:
        return [paths[0], "-i", "-w", str(pid)]
    inhibit, tail = paths
    return [inhibit, "--what=sleep:idle", f"--who={WHO}", f"--why=tl step rounds {backlog}", "--mode=block",
            tail, f"--pid={pid}", "-f", "/dev/null"]


@contextmanager
def awake(host: Host, pid: int, backlog: str, log: Callable[[str], None], clock: Callable[[], float],
          say: Callable[[str], object]) -> Generator[None]:
    """The helper for the block's life, stopped on every way out (return, exception, `KeyboardInterrupt`); without one,
    the two lines and the block runs anyway."""
    argv = command(host, pid, backlog)
    if isinstance(argv, list):
        try:
            helper: Helper | Unavailable = host.spawn(argv)
        except OSError as error:
            helper = Unavailable("start", f"{argv[0]}: {type(error).__name__}: {error}")
    else:
        helper = argv
    if isinstance(helper, Unavailable):
        _line(log, clock, backlog, "unavailable:" + helper.word)
        say(f"Keep-awake unavailable ({helper.detail}); the rounds run anyway")
        yield
        return
    try:
        helper.replay()
        _line(log, clock, backlog, "started", f"pid={helper.pid}")
        yield
    finally:
        helper.stop()


def _line(log: Callable[[str], None], clock: Callable[[], float], backlog: str, *words: str) -> None:
    """Best effort: the rounds say themselves when their log stops being written."""
    try:
        log(stamped(clock(), backlog, "rounds", "keep_awake", *words))
    except (OSError, EvidenceError):
        return
