"""The replan prompt carries the tree's diff stat and a budget for looking, and only on a replan."""
import sys
from pathlib import Path
from types import SimpleNamespace

from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.git import RealGit
from taskloop.app.plan.prompt import REPLAN_CALLS, PlanPrompt
from taskloop.contracts.env import snapshot


class StatGit(RealGit):
    def diff(self, d, a, b, exclude=None, stat=False):
        return " a.py | 2 +-\n"


def host(tree="abc"):
    ledger = SimpleNamespace(text=lambda: "")
    return SimpleNamespace(wt="/wt", checkout=SimpleNamespace(tree_hash=lambda: tree, base_sha=lambda: "base"),
                           hand=SimpleNamespace(rounds_text=lambda: "- stage 1, round 1 (review); sent back: x\n"),
                           routing=SimpleNamespace(ledger=lambda: ledger))


class Digest(Case):
    def test_a_replan_gets_the_diff_stat_and_the_budget(self):
        text = PlanPrompt(host(), StatGit(snapshot())).history({"stages": []}, False)
        assert "<tree>\na.py | 2 +-\n</tree>" in text
        assert f"at most {REPLAN_CALLS} files" in text
        assert "sent back: x" in text

    def test_a_first_plan_gets_neither(self):
        assert PlanPrompt(host(), StatGit(snapshot())).history(None, False) == ""

    def test_no_tree_says_nothing_changed(self):
        assert "(no file changed yet)" in PlanPrompt(host(tree=""), StatGit(snapshot())).history(None, True)
