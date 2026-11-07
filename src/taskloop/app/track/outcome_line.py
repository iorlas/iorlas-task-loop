"""The run's append-only output and final outcome line."""
import fcntl
import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text
from tlkernel import wire
from tlkernel.enums import Result
from tlkernel.run import RunReport

from taskloop.app.track import console

say = console.say


def append_output(stream: Any) -> Any:
    """Write a stream that is a file at the end of that file, wherever another writer left it: a second
    `run-task ... > log` on the same log truncates it, and a live run writing on at its old offset leaves a hole of NUL
    bytes. A terminal, a pipe or a stream with no descriptor is left as it is."""
    try:
        fd = stream.fileno()
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except (OSError, ValueError):  # no descriptor (a captured stream) or a closed one: nothing to keep in order
        return
    if regular:
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_APPEND)


def pause_line(rec: RunReport) -> Any:
    """A paused run's one line for whoever reran it by hand: the exact time the lane is back (tl-bxk.10.6)."""
    if rec.outcome is not Result.PAUSED:
        return ""
    due = rec.retry_after or 0.0
    if not due:
        return f"PAUSED {rec.bead}: no time the lane frees (login, network or setup); rerun when fixed: tl run-task {rec.bead}"
    return "PAUSED {}: the lane is back at {}; rerun then: tl run-task {}".format(
        rec.bead, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(due)), rec.bead)


def report(a: Any, rec: RunReport) -> Any:
    """The outcome as the run's last stdout line, and in --outcome-file when the loop names one."""
    line = json.dumps(wire.dump(rec), ensure_ascii=False)
    if getattr(a, "outcome_file", None):
        atomic_write_text(Path(a.outcome_file), line + "\n", fsync=False)
    say(line)
