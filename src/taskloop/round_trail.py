"""The round's moves in the order performed, each also a line of the round log (`round.run_round`'s trail)."""

from collections.abc import Callable
from typing import Final, get_args

from taskloop.evidence_files import EvidenceError
from taskloop.operations import Failed, Move, Quiet, Round
from taskloop.round_log import fixed, ident, stamped
from taskloop.selection import Skip
from taskloop.slots import unusable

# The admission phase's own skip words (`selection.order`): their lines stand while a round does not read the ready rows.
RANKED_SKIPS: Final = frozenset(get_args(Skip.__value__))


def key(move: Move) -> tuple[str, str, str, str]:
    return move.task_id, move.action, move.word, move.attempt_id


class Trail:
    """The round's moves in the order performed, each also appended to the round log as fixed words only, unless it is
    in `quiet`; a failed write never changes the round, it only clears `logged`. `ranked`: admission read and ordered the
    ready rows this round (else the previous round's admission skips are carried on as written, unchanged)."""

    def __init__(self, log: Callable[[str], None], clock: Callable[[], float], backlog: str, quiet: Quiet | None) -> None:
        self.log, self.clock, self.backlog, self.quiet = log, clock, backlog, quiet
        self.moves: list[Move] = []
        self.written: set[tuple[str, str, str, str]] = set()
        self.logged, self.wrote, self.ranked = True, False, False

    def _write(self, key: tuple[str, str, str, str], *words: str) -> None:
        if self.quiet is not None and key in self.quiet:
            self.written.add(key)
            return
        self.wrote = True
        try:
            self.log(stamped(self.clock(), self.backlog, *words))
        except (OSError, EvidenceError):
            self.logged = False
            return
        self.written.add(key)

    def add(self, move: Move) -> None:
        self.moves.append(move)
        words = [fixed(each) for each in move.word.split(" ")]
        step = [fixed(move.step)] if move.step else []  # an attempt-bearing move names its attempt's step after the task
        self._write(key(move), ident(move.task_id), *step, move.action, *words, *([ident(move.attempt_id)] if move.attempt_id else []))

    def close(self, stopped: str) -> Round:
        """The closing line, unless quiet: no move line written and the same line (move count and stopped word) as the
        previous round's."""
        if not self.ranked and self.quiet is not None:  # a round with no free slot never reaches the ready rows
            self.written |= {key for key in self.quiet if key[1] == "skip" and key[2] in RANKED_SKIPS}
        key = ("", "stopped", stopped, f"moves={len(self.moves)}")
        if self.wrote and self.quiet is not None and key in self.quiet:
            self.quiet = self.quiet - {key}  # a round that wrote a move line always closes it
        self._write(key, "round", f"moves={len(self.moves)}", *([f"stopped={fixed(stopped)}"] if stopped else []))
        written = frozenset(self.written) if self.logged else frozenset()
        return Round(self.backlog, tuple(self.moves), stopped, self.logged, written)

    def unusable(self, task_id: str, refused: Failed) -> None:
        """`unusable:<slot>:<why>` for each slot no attempt holds yet no admission can use (missing, dirty, redirected, on a
        branch...): what `no_free_slot` does not say."""
        for each in unusable(refused.slots):
            self.add(Move(task_id, "report", f"unusable:{each.name}:{each.reason}", detail=str(each.path)))
