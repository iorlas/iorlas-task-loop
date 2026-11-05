"""Run a child to its end and hand back its whole output: as text (:func:`capture`) or as exact bytes (:func:`capture_bytes`)."""

from __future__ import annotations

import contextlib
import os
import select
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Any

from stream_proc.hold import popen_held
from stream_proc.runner import _release, _wait
from stream_proc.tree import stop_tree

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

TIMEOUT_EXIT = 124  # the exit code of coreutils ``timeout``


@dataclass(frozen=True, slots=True)
class Captured:
    """What :func:`capture` saw: ``exit`` (124 on a timeout, ``-signal`` when a signal ended the child), the decoded
    ``out`` and ``err`` in full, ``secs`` wall time, ``timed_out``, and ``survivors`` (pids left after the stop)."""

    exit: int
    out: str
    err: str
    secs: float
    timed_out: bool
    survivors: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CapturedBytes:
    """What :func:`capture_bytes` saw: like :class:`Captured`, but ``out`` and ``err`` are the exact bytes (b"" when
    ``capture=False``). On a timeout they hold what the child wrote before it was stopped."""

    exit: int
    out: bytes
    err: bytes
    secs: float
    timed_out: bool
    survivors: tuple[int, ...] = ()


def _slurp(stream: IO[bytes] | None, sink: list[bytes], quit_: threading.Event) -> None:
    """Read ``stream`` to EOF into ``sink``; polls so ``quit_`` ends it even when a stranger holds the pipe open."""
    if stream is None:
        return
    fd = stream.fileno()
    while not quit_.is_set():
        if not select.select([fd], [], [], 0.05)[0]:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return
        if not chunk:
            return
        sink.append(chunk)


def _feed(stream: IO[bytes] | None, data: bytes, quit_: threading.Event) -> None:
    """Write ``data`` to ``stream`` as the child takes it, then close; a child that stops reading (or exits) ends it quietly."""
    if stream is None:
        return
    fd = stream.fileno()
    os.set_blocking(fd, False)
    view = memoryview(data)
    try:
        while view and not quit_.is_set():
            if not select.select([], [fd], [], 0.05)[1]:
                continue
            try:
                view = view[os.write(fd, view[:65536]) :]
            except BlockingIOError:
                continue
    except OSError:  # BrokenPipeError: the child exited without reading it all
        pass
    finally:
        with contextlib.suppress(OSError):
            stream.close()


def capture_bytes(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    input: bytes | None = None,  # noqa: A002 - subprocess.run's name
    stdin: int | IO[Any] | None = subprocess.DEVNULL,
    capture: bool = True,
    grace: float = 5.0,
    drain: float = 2.0,
) -> CapturedBytes:
    """Run ``argv`` in a session of its own to its end; stdout and stderr come back as exact bytes (no decoding, no newline conversion).

    ``stdin`` is a ``subprocess`` value: ``subprocess.DEVNULL`` (default), ``None`` (inherit ours), a descriptor or a
    file. ``input`` feeds bytes instead (a pipe, written while the output is read, so large input and large output never
    deadlock; a child that exits without reading it all is not an error); give ``input`` or ``stdin``, not both
    (``ValueError``). ``capture=False`` leaves stdout and stderr inherited and returns them empty. The child is always
    a session leader, so even with an inherited stdin it has no controlling terminal (no tty job control, no ``/dev/tty``).

    The wait is on the child, not on its pipes: ``timeout`` is the wall limit for the child; hitting it stops the whole
    tree (``grace``) and returns exit 124 with ``timed_out`` set, not an exception, like :func:`capture`, with the partial
    output in ``out``/``err``. After the child ended (or was stopped) the pipes are read for at most ``drain`` more seconds,
    so a process that outlived the child and still holds a pipe (``sleep 30 &``) delays the result by ``drain``, never by
    its own lifetime; whatever arrived by then is returned. An exception that unwinds the wait (KeyboardInterrupt, a raising
    SIGTERM handler, even one landing during the spawn) stops the tree first and goes on. The output is not capped.
    """
    if input is not None and stdin != subprocess.DEVNULL:
        msg = "give input or stdin, not both"
        raise ValueError(msg)
    t0 = time.monotonic()
    pipe = subprocess.PIPE if capture else None
    p, hold = popen_held(
        list(argv),
        cwd=cwd,
        env=None if env is None else dict(env),
        stdin=subprocess.PIPE if input is not None else stdin,
        stdout=pipe,
        stderr=pipe,
        start_new_session=True,
    )
    out: list[bytes] = []
    err: list[bytes] = []
    quit_ = threading.Event()
    threads = [
        threading.Thread(target=_slurp, args=(p.stdout, out, quit_), daemon=True),
        threading.Thread(target=_slurp, args=(p.stderr, err, quit_), daemon=True),
    ]
    if input is not None:
        threads.append(threading.Thread(target=_feed, args=(p.stdin, input, quit_), daemon=True))
    survivors: tuple[int, ...] = ()
    timed = False
    try:
        try:
            hold.replay()
            for thread in threads:
                thread.start()
            timed = _wait(p, t0=t0, last=[t0], timeout=timeout, idle=None, stop=None) is not None
            if timed:
                survivors = stop_tree(p, grace=grace)
        except BaseException:
            stop_tree(p, grace=grace)
            raise
        end = time.monotonic() + drain
        for thread in threads:
            if thread.is_alive():
                thread.join(max(0.0, end - time.monotonic()))
    finally:
        _release(p, threads, quit_)
    code = p.returncode
    exit_ = TIMEOUT_EXIT if timed else (code if code is not None else -1)
    return CapturedBytes(exit_, b"".join(out), b"".join(err), time.monotonic() - t0, timed, survivors)


def capture(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    tick: Callable[[], None] | None = None,
    poll_s: float = 0.2,
    grace: float = 5.0,
) -> Captured:
    """:func:`capture_bytes` with stdin /dev/null, stdout and stderr decoded as text (UTF-8, bad bytes replaced, newlines kept as written).

    ``timeout`` is the wall limit; hitting it stops the whole tree and reports exit 124. ``tick`` runs every ``poll_s``
    seconds on a helper thread while the child lives, and once more after it ends (a heartbeat;
    an exception from it is ignored). An exception that
    unwinds the wait stops the tree first. The output is not capped: it all sits in memory.
    """
    done = threading.Event()
    helper = None
    if tick is not None:
        beat = tick

        def ticker() -> None:
            while not done.wait(poll_s):
                with contextlib.suppress(Exception):
                    beat()

        helper = threading.Thread(target=ticker, daemon=True)
        helper.start()
    try:
        res = capture_bytes(argv, cwd=cwd, env=env, timeout=timeout, grace=grace, drain=5.0)
    finally:
        done.set()
        if helper is not None:
            helper.join(2)
    if tick is not None:
        with contextlib.suppress(Exception):
            tick()  # a failing heartbeat never costs the result
    return Captured(
        res.exit, res.out.decode("utf-8", "replace"), res.err.decode("utf-8", "replace"), res.secs, res.timed_out, res.survivors
    )
