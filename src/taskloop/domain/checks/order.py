"""CheckOrder: the order a round runs its checks in, cheapest first."""
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from taskloop.contracts.checks import Check, Durations
from taskloop.domain.checks.durations import expected_secs

RANK: Final = MappingProxyType({"static": 0, "tests": 1, "acceptance": 2})
RANK_ACCEPTANCE_FIRST: Final = MappingProxyType({"static": 0, "acceptance": 1, "tests": 2})


class CheckOrder:
    """By the median of earlier runs of the same command (unknown = cheap), so a red verdict comes before the slow Unity runs;
    `acceptance_first` puts acceptance before tests at equal cost (a round that failed only in acceptance: lifesim-fdyo reran 11
    minutes of unity tests before a 3-second verdict check failed). A check reading $TL_CHECK_LOG_X goes after X, and `late` (the
    Unity group) after every other check whose dependencies allow it. A cycle of dependencies is broken by declaration order."""

    def __init__(self, history: Durations, acceptance_first: bool = False) -> None:
        self.history = history
        self.rank = RANK_ACCEPTANCE_FIRST if acceptance_first else RANK

    def sort(self, checks: Sequence[Check], deps: Mapping[int, Sequence[int]], late: frozenset[int] = frozenset()) -> list[int]:
        """The indexes of `checks` in run order. deps: {index: [indexes it must come after]}."""
        keyed = sorted(range(len(checks)), key=lambda i: (
            i in late, expected_secs(checks[i].cmd, self.history), self.rank.get(checks[i].group, 1), i))
        placed: set[int] = set()
        out: list[int] = []
        left = list(keyed)
        while left:
            pick = next((i for i in left if all(d in placed or d == i for d in deps.get(i, ()))), left[0])
            left.remove(pick)
            placed.add(pick)
            out.append(pick)
        return out
