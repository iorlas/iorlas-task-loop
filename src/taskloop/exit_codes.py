"""Application CLI exit policy. No reliable result is exit 3 and safe to retry; inspection errors remain exit 1.
Argparse owns usage exit 2. Nothing here runs, reads or writes."""

from enum import IntEnum
from typing import Final

from taskloop import profile
from taskloop.drain.models import Reason
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


class ExitCode(IntEnum):
    SUCCESS = 0
    REFUSED = 1
    UNKNOWN = 3
    INTERRUPTED = 130  # 128 + SIGINT: the shell's convention for an interrupted command


def profile_exit_code(result: profile.Resolved | profile.Refused | profile.Unavailable) -> ExitCode:
    """Profile unavailable means no verdict was possible; another read is safe."""
    match result:
        case profile.Resolved():
            return ExitCode.SUCCESS
        case profile.Refused():
            return ExitCode.REFUSED
        case profile.Unavailable():
            return ExitCode.UNKNOWN


def _round_exit(result: Round) -> ExitCode:
    """3 when admission stopped on an unknown or a move's word is one, a verify's `branch=` word included, as a publish
    move's (rerunning is safe); 1 when the round's own inputs were refused; else 0 (a per-task refusal, a held release
    and a leaked claim, reported as its own move, do not change the exit)."""
    words = [result.stopped, *(word.removeprefix("branch=") for move in result.moves for word in move.word.split(" "))]
    if any(word.startswith(UNKNOWN_WORDS) or word == "unknown" for word in words):
        return ExitCode.UNKNOWN
    return ExitCode.REFUSED if result.stopped.startswith("refused:") else ExitCode.SUCCESS


def exit_code(result: Result) -> ExitCode:
    """0 done or already so (a graceful rounds stop too); 1 refused; 3 unknown, re-running is safe; 130 an abrupt rounds
    stop or a land interrupted by Ctrl-C (2, usage, is argparse's). Rounds never end 3: they rerun by themselves."""
    match result:
        case Failed(reason=reason) if reason == INTERRUPTED:
            return ExitCode.INTERRUPTED
        case Failed(kind=kind):
            return ExitCode.UNKNOWN if kind in UNKNOWN_KINDS else ExitCode.REFUSED
        case Adoption(slots=slots):
            reasons = {each.reason for each in slots if isinstance(each, NotAdopted)}
            return (ExitCode.UNKNOWN if reasons & {"git_unavailable", "store_unavailable"}
                    else ExitCode.REFUSED if reasons else ExitCode.SUCCESS)
        case Round():
            return _round_exit(result)
        case Ended(reason=reason):
            return (ExitCode.SUCCESS if reason in {"interrupted", Reason.DRAINING, Reason.DRAINED} else
                    ExitCode.INTERRUPTED if reason == "abrupt" else ExitCode.REFUSED)
        case _:
            return ExitCode.SUCCESS
