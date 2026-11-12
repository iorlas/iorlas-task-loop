"""The exit code of every step command's result: 0 done (a graceful rounds stop too), 1 refused, 3 unknown, 130 an abrupt
rounds stop or an interrupted land. Command surface policy over operations' values; nothing here runs, reads or writes."""

from typing import Final

from taskloop.land_guide import INTERRUPTED
from taskloop.operations import (
    UNKNOWN_KINDS,
    Adoption,
    Ended,
    Failed,
    Round,
)
from taskloop.result_data import Result
from taskloop.slots import NotAdopted

UNKNOWN_WORDS: Final = tuple(kind + ":" for kind in UNKNOWN_KINDS)
ABRUPT: Final = 130  # 128 + SIGINT: the shell's convention for an interrupted command


def _round_exit(result: Round) -> int:
    """3 when admission stopped on an unknown or a move's word is one, a verify's `branch=` word included, as a publish
    move's (rerunning is safe); 1 when the round's own inputs were refused; else 0 (a per-task refusal, a held release
    and a leaked claim, reported as its own move, do not change the exit)."""
    words = [result.stopped, *(word.removeprefix("branch=") for move in result.moves for word in move.word.split(" "))]
    if any(word.startswith(UNKNOWN_WORDS) or word == "unknown" for word in words):
        return 3
    return 1 if result.stopped.startswith("refused:") else 0


def exit_code(result: Result) -> int:
    """0 done or already so (a graceful rounds stop too); 1 refused; 3 unknown, re-running is safe; 130 an abrupt rounds
    stop or a land interrupted by Ctrl-C (2, usage, is argparse's). Rounds never end 3: they rerun by themselves."""
    match result:
        case Failed(reason=reason) if reason == INTERRUPTED:
            return ABRUPT
        case Failed(kind=kind):
            return 3 if kind in UNKNOWN_KINDS else 1
        case Adoption(slots=slots):
            reasons = {each.reason for each in slots if isinstance(each, NotAdopted)}
            return 3 if reasons & {"git_unavailable", "store_unavailable"} else 1 if reasons else 0
        case Round():
            return _round_exit(result)
        case Ended(reason=reason):
            return 0 if reason == "interrupted" else ABRUPT if reason == "abrupt" else 1
        case _:
            return 0
