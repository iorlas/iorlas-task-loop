"""The replan prompt carries the tree's diff stat and a budget for looking, and only on a replan."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.plan.prompt import REPLAN_CALLS, PlanPrompt


def host(tree="abc"):
    ledger = SimpleNamespace(text=lambda: "")
    return SimpleNamespace(checkout=SimpleNamespace(tree_hash=lambda: tree, base_sha=lambda: "base"), git=lambda *a: " a.py | 2 +-\n",
                           hand=SimpleNamespace(rounds_text=lambda: "- stage 1, round 1 (review); sent back: x\n"),
                           routing=SimpleNamespace(ledger=lambda: ledger))


class Digest(unittest.TestCase):
    def test_a_replan_gets_the_diff_stat_and_the_budget(self):
        text = PlanPrompt(host()).history({"stages": []}, False)
        self.assertIn("<tree>\na.py | 2 +-\n</tree>", text)
        self.assertIn(f"at most {REPLAN_CALLS} files", text)
        self.assertIn("sent back: x", text)

    def test_a_first_plan_gets_neither(self):
        self.assertEqual(PlanPrompt(host()).history(None, False), "")

    def test_no_tree_says_nothing_changed(self):
        self.assertIn("(no file changed yet)", PlanPrompt(host(tree="")).history(None, True))


if __name__ == "__main__":
    unittest.main()
