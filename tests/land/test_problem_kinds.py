"""Every ProblemKind is handled by every table keyed by it: a new kind cannot be forgotten (a missing STALE ended a 70-minute run)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

# isort: split
from taskloop.app.land.fix_outside import CAUSE, FixOutside
from taskloop.app.land.gate import Problem, ProblemKind
from taskloop.domain.prompts.land import FIX_GOAL, FIX_TEXT, FIX_WHAT

NO_FIX_ROUND = {ProblemKind.STALE}  # main or the tree moved under the gate: the gate runs again, nobody fixes anything


class EveryKind(unittest.TestCase):
    def test_every_kind_with_a_fix_round_is_in_every_fix_table(self):
        for kind in ProblemKind:
            if kind in NO_FIX_ROUND:
                continue
            with self.subTest(kind=kind):
                for table in (CAUSE, FIX_WHAT, FIX_GOAL, FIX_TEXT):
                    self.assertIn(kind, table)

    def test_a_kind_without_a_fix_round_is_in_no_fix_table(self):
        for kind in NO_FIX_ROUND:
            self.assertIsNone(CAUSE[kind])
            for table in (FIX_WHAT, FIX_GOAL, FIX_TEXT):
                self.assertNotIn(kind, table)

    def test_stale_returns_without_moving_or_fixing(self):
        host = Mock()
        FixOutside(host).run(Problem(ProblemKind.STALE, "base moved"))
        self.assertEqual(host.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
