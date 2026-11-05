"""Child processes through the vendored stream-proc: the one place task-loop spawns, waits for and stops a process tree.

Nothing here (nor anywhere in the repo outside `_vendor/`) sends a signal: a stop is `stream_proc.stop_tree`, a liveness read is
`stream_proc.alive`. A process this program did not spawn (the dashboard server, a recorded lock holder) is stopped through a
`PidHandle`, which gives stop_tree the few attributes of a `Popen` it uses; the process-group detail stays inside stream-proc."""

import subprocess
import threading
from collections.abc import Callable, Mapping
from typing import Any

import stream_proc
from stream_proc import TermHold, alive, popen_held, proc_start, stop_tree
from stream_proc.proctable import has_table

from taskloop.adapters import deadline

STOP_GRACE_S = 5.0

__all__ = ["TermHold", "alive", "popen_held", "proc_start", "stop_tree"]


def run_bytes(argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
              timeout: float | None = None, input: bytes | None = None, capture: bool = True,
              inherit_stdin: bool = True) -> subprocess.CompletedProcess[bytes]:
    """A captured runner using stream-proc's held spawn and tree stop, preserving binary data and stdin.

    stream_proc.run only offers decoded line callbacks and /dev/null stdin. Use its lifecycle here with communicate
    for exact bytes, input and inherited descriptors; the vendored shelf stays byte-identical to its recorded tag.
    """
    timeout = deadline.remaining(timeout)
    p, hold = popen_held(argv, cwd=cwd, env=env, start_new_session=True,
                         stdin=subprocess.PIPE if input is not None else (None if inherit_stdin else subprocess.DEVNULL),
                         stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    try:
        hold.replay()
        stdout, stderr = p.communicate(input=input, timeout=timeout)
        deadline.check()
    except subprocess.TimeoutExpired as err:
        stop_tree(p, grace=STOP_GRACE_S)
        # Bound the drain even if an unrelated process inherited a pipe; retain the complete partial output.
        try:
            err.output, err.stderr = p.communicate(timeout=2.0)
        except subprocess.TimeoutExpired as drain:
            err.output = drain.output if drain.output is not None else err.output
            err.stderr = drain.stderr if drain.stderr is not None else err.stderr
        deadline.check()
        raise
    except BaseException:
        stop_tree(p, grace=STOP_GRACE_S)
        raise
    finally:
        for pipe in (p.stdin, p.stdout, p.stderr):
            if pipe is not None:
                pipe.close()
    return subprocess.CompletedProcess(argv, p.wait(), stdout or b"", stderr or b"")


def run(argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
        timeout: float | None = None, input: str | None = None, capture: bool = True,
        inherit_stdin: bool = True) -> subprocess.CompletedProcess[str]:
    """UTF-8 text capture, with subprocess.run's newline conversion and timeout exception."""
    res = run_bytes(argv, cwd=cwd, env=env, timeout=timeout, input=None if input is None else input.encode("utf-8"),
                    capture=capture, inherit_stdin=inherit_stdin)
    out, err = (s.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
                for s in (res.stdout or b"", res.stderr or b""))
    return subprocess.CompletedProcess(argv, res.returncode, out, err)


Ran = stream_proc.Captured


def capture(
    argv: list[str],
    cwd: str | None,
    env: Mapping[str, str] | None,
    timeout_s: float,
    tick: Callable[[], None] | None = None,
    poll_s: float = 0.2,
) -> Ran:
    """Run a child to its end (or `timeout_s`), collecting stdout and stderr (stream-proc's capture, under the run's deadline)."""
    res = stream_proc.capture(argv, cwd=cwd, env=env, timeout=deadline.remaining(timeout_s), tick=tick, poll_s=poll_s,
                              grace=STOP_GRACE_S)
    deadline.check()
    return res


def stream(argv: list[str], *, cwd: str | None, env: Mapping[str, str], on_output: Callable[[str], None], timeout_s: float | None,
           stop: threading.Event | None, grace: float) -> stream_proc.Result:
    """One child in a session of its own, its lines (stdout and stderr) to `on_output`; stream-proc stops its tree at the limit, on `stop`
    and on any exception, and proves it dead."""
    res = stream_proc.run(argv, cwd=cwd, env=env, on_stdout=on_output, on_stderr=on_output,
                          timeout=deadline.remaining(timeout_s), stop=stop, grace=grace)
    deadline.check()
    return res


def spawn(argv: list[str] | str, **kw: Any) -> subprocess.Popen[bytes]:
    """A child that outlives this call (a detached server, a digest): through stream-proc's held spawn, in a session of its own."""
    kw.setdefault("start_new_session", True)
    p, hold = popen_held(argv, **kw)
    try:
        hold.replay()  # a SIGTERM that arrived during the spawn runs the real handler now, with the child in hand
    except BaseException:
        stop_tree(p, grace=STOP_GRACE_S)
        raise
    return p


PidHandle = stream_proc.PidHandle
stop_pid = stream_proc.stop_pid


Proc = stream_proc.Proc


def table() -> dict[int, Proc] | None:
    """Every process the system lists, through stream-proc (/proc on Linux, libproc on macOS; no ps, no signal): None where it lists
    none at all (no readable table), so a caller reads that as "cannot tell", never as "nothing runs"."""
    if not has_table():
        return None
    rows = stream_proc.table()
    return rows or None


def stop_in_thread(p: Any, grace: float) -> threading.Thread:
    """`stop_tree` on a thread, so the caller's loop goes on while the tree ends. -> the thread."""
    th = threading.Thread(target=stop_tree, args=(p,), kwargs={"grace": grace}, daemon=True)
    th.start()
    return th
