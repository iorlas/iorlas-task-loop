"""What a run prints while it works: the lines of the records a person reads. Everything else is for the dashboard only."""

import time
from collections.abc import Callable

from taskloop.contracts.log import CmdStart, EngineLog, Note, StepStart, Warn

QUIET = frozenset(
    {
        "run_start",
        "step_end",
        "call_start",
        "call_end",
        "cmd_end",
        "check_start",
        "check_end",
        "gate_start",
        "gate_end",
        "land_try",
        "wait_start",
        "wait_end",
        "lock",
        "unlock",
        "vendor_error",
        "kill",
        "transition",
        "reload",
        "checks",
        "close",
    }
)


def line(verbose: bool = True) -> Callable[[EngineLog], str | None]:
    """The console line of a record: [HH:MM:SS] and its text; a command only in verbose mode; a warning after a mark."""

    def render(rec: EngineLog) -> str | None:
        if isinstance(rec, CmdStart) and not verbose:
            return None
        text = rec.text if isinstance(rec, (StepStart, CmdStart, Note, Warn)) else None
        if text is None:
            return None
        return "[%s] %s%s" % (time.strftime("%H:%M:%S", time.localtime(rec.t)), "⚠ " if isinstance(rec, Warn) else "", text)

    return render
