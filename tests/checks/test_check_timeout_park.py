"""A check stopped at its wall limit is not the writer's to fix. The engine run that parks on it is in test_stages (Fdyo)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.checks import res

from taskloop.app.checks import evidence
from taskloop.contracts.checks import CheckResult


def result(**kw) -> CheckResult:
    return res(**kw)


class Decision(unittest.TestCase):
    def test_table(self):
        slow = result(id="u", exit=124, wall_hit=True, wall_min=2.0)
        rows = [("no failed check", [], None), ("red, not timed out", [result()], None),
                ("exit 124 of the command's own is not the engine's limit", [result(exit=124)], None),
                ("the wall hit", [result(), slow], slow)]
        for name, failed, want in rows:
            with self.subTest(name):
                self.assertIs(evidence.timed_out(failed), want)

    def test_the_reason_names_the_check_and_the_limit(self):
        self.assertEqual(evidence.timeout_why(result(id="unity", wall_min=2.0)), "check unity timed out after 2 min (wall_min=2)")


if __name__ == "__main__":
    unittest.main()
