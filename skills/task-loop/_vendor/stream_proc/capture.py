"""Run a child to its end and hand back its whole output as text."""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stream_proc.runner import run

if TYPE_CHECKING:
    import os
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
    """:func:`run` to the end, stdout and stderr collected as text (UTF-8, bad bytes replaced, newlines kept as written).

    ``timeout`` is the wall limit; hitting it stops the whole tree and reports exit 124. ``tick`` runs every ``poll_s``
    seconds on a helper thread while the child lives, and once more after it ends (a heartbeat;
    an exception from it is ignored). An exception that
    unwinds the wait stops the tree first, as in :func:`run`. The output is not capped: it all sits in memory.
    """
    out: list[str] = []
    err: list[str] = []
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
        res = run(argv, cwd=cwd, env=env, on_stdout=out.append, on_stderr=err.append, timeout=timeout, grace=grace)
    finally:
        done.set()
        if helper is not None:
            helper.join(2)
    if tick is not None:
        with contextlib.suppress(Exception):
            tick()  # a failing heartbeat never costs the result
    timed = res.timed_out is not None
    code = TIMEOUT_EXIT if timed else (res.returncode if res.returncode is not None else -(res.signal or 1))
    return Captured(code, "".join(out), "".join(err), res.secs, timed, res.survivors)
