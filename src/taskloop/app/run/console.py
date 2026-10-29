"""What a run prints while it works: the lines of the records a person reads. Everything else is for the dashboard only."""

import sys
import time
from collections.abc import Callable

from taskloop.contracts.log import Assumed, CmdStart, EngineLog, Note, StepStart, Stuck, Warn

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
        "beat",
        "said",
        "close",
    }
)


def line(verbose: bool = True) -> Callable[[EngineLog], str | None]:
    """The console line of a record: [HH:MM:SS] and its text; a command only in verbose mode; a warning after a mark."""

    def render(rec: EngineLog) -> str | None:
        if isinstance(rec, CmdStart) and not verbose:
            return None
        text = rec.text if isinstance(rec, (StepStart, CmdStart, Note, Warn)) else None
        if isinstance(rec, Assumed):
            text = "assumed: " + rec.text
        elif isinstance(rec, Stuck):
            text = f"stuck in {rec.step or 'the run'}: " + ("silent past the limit" if rec.why == "silent" else "the same checks red")
        if text is None:
            return None
        mark = "⚠ " if isinstance(rec, (Warn, Stuck)) else ""
        return "[{}] {}{}".format(time.strftime("%H:%M:%S", time.localtime(rec.t)), mark, text)

    return render


def say(text: str) -> None:
    """Print whatever the console can show (a console may not print ⚠): never crash on output."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, "replace").decode(enc), flush=True)
