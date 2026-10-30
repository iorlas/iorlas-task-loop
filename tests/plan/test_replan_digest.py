"""The replan prompt carries the tree's diff stat and a budget for looking, and only on a replan."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.git import RealGit
from taskloop.app.plan.prompt import REPLAN_CALLS, PlanPrompt


class StatGit(RealGit):
    def diff(self, d, a, b, exclude=None, stat=False):
        return " a.py | 2 +-\n"


def host(tree="abc"):
    ledger = SimpleNamespace(text=lambda: "")
    return SimpleNamespace(wt="/wt", checkout=SimpleNamespace(tree_hash=lambda: tree, base_sha=lambda: "base"),
                           hand=SimpleNamespace(rounds_text=lambda: "- stage 1, round 1 (review); sent back: x\n"),
                           routing=SimpleNamespace(ledger=lambda: ledger))


class Digest(unittest.TestCase):
    def test_a_replan_gets_the_diff_stat_and_the_budget(self):
        text = PlanPrompt(host(), StatGit()).history({"stages": []}, False)
        self.assertIn("<tree>\na.py | 2 +-\n</tree>", text)
        self.assertIn(f"at most {REPLAN_CALLS} files", text)
        self.assertIn("sent back: x", text)

    def test_a_first_plan_gets_neither(self):
        self.assertEqual(PlanPrompt(host(), StatGit()).history(None, False), "")

    def test_no_tree_says_nothing_changed(self):
        self.assertIn("(no file changed yet)", PlanPrompt(host(tree=""), StatGit()).history(None, True))


if __name__ == "__main__":
    unittest.main()
