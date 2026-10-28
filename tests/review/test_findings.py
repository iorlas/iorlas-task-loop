"""What a review's answer means: which findings block, which items the engine files, which acceptance item has no evidence, and a report
of the 50 labelled send-backs of study 81 (a report, not a gate)."""
import itertools
import json
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.domain.review import findings as fnd
from taskloop.domain.review.ledger import Ledger

SENDBACKS = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "sendbacks.json").read_text(encoding="utf-8"))


def finding(severity="high", scenario="x=None raises", fix="handle None"):
    return {"file": "a.py", "line": 1, "severity": severity, "axis": "spec", "category": "logic", "fix": fix, "scenario": scenario}


class Blocking(unittest.TestCase):
    def test_a_finding_blocks_only_at_high_with_a_failure_scenario(self):
        for sev, scenario in itertools.product(("low", "medium", "high"), ("", "  ", "input x gives y")):
            with self.subTest(sev=sev, scenario=scenario):
                self.assertEqual(fnd.blocks(finding(sev, scenario)), sev == "high" and bool(scenario.strip()))

    def test_later_rounds_drop_the_lows(self):
        got = [finding("low"), finding("high")]
        self.assertEqual(len(fnd.lows_after_first(got, 1)), 2)
        self.assertEqual([f["severity"] for f in fnd.lows_after_first(got, 2)], ["high"])


class SpecAxis(unittest.TestCase):
    ITEMS: ClassVar[Any] = [("A1", "f.txt exists"), ("A2", "the log says done")]

    def test_every_item_mapped_gives_no_finding(self):
        crit = [{"item": "A1", "status": "met", "evidence": "check"}, {"item": "A2", "status": "engine", "evidence": ""}]
        self.assertEqual(fnd.unmapped(self.ITEMS, crit), [])

    def test_one_unmapped_item_is_a_blocking_spec_finding(self):
        got = fnd.unmapped(self.ITEMS, [{"item": "A1", "status": "met", "evidence": "check"}])
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["axis"], fnd.blocks(got[0])), ("spec", True))
        self.assertIn("A2", got[0]["fix"])

    def test_met_without_evidence_is_unmapped(self):
        self.assertEqual(len(fnd.unmapped(self.ITEMS[:1], [{"item": "A1", "status": "met", "evidence": " "}])), 1)

    def test_an_unmet_criterion_joins_the_unmet_list_once(self):
        crit = [{"item": "A1", "status": "unmet", "evidence": "no file"}]
        self.assertEqual(fnd.unmet_from(crit, ["A1: no file"]), ["A1: no file"])


class Routing(unittest.TestCase):
    """Wording from the labelled send-backs (study 81): bd actions are the engine's, a remark is no gap, a real gap stays."""

    def route(self, unmet=(), findings=(), plan=None):
        return fnd.route(list(unmet), list(findings), Ledger(plan, []))

    def test_a_bd_demand_is_filed_not_sent_back(self):
        for said in ("beads to file", "close/fold 2 beads (bd action)", "approval + follow-up beads unfiled",
                     "screenshot judgement needs a bd comment (writer barred from bd)"):
            with self.subTest(said):
                r = self.route([said])
                self.assertEqual((r.unmet, len(r.files)), ([], 1))

    def test_goal_is_met_is_dropped_not_unmet(self):
        r = self.route(["the stage goal is met"])
        self.assertEqual((r.unmet, r.files, len(r.dropped)), ([], [], 1))

    def test_a_mixed_item_keeps_its_real_gap(self):
        r = self.route(["README table stale vs evidence; bd follow-ups unfiled"])
        self.assertEqual((r.unmet, len(r.files)), (["README table stale vs evidence"], 1))

    def test_a_finding_asking_for_a_bead_is_filed_and_leaves_the_findings(self):
        r = self.route(findings=[finding(fix="file the follow-up beads"), finding(fix="handle None")])
        self.assertEqual(([f["fix"] for f in r.findings], len(r.files)), (["handle None"], 1))

    def test_an_item_the_plan_defers_is_dropped(self):
        plan = {
            "cases": [
                {
                    "criterion": "tests for the parser edge cases",
                    "proved_by": "leftover",
                    "via": "follow-up bead for parser edge case tests",
                }
            ]
        }
        self.assertEqual(self.route(["Add tests for the parser edge cases"], plan=plan).unmet, [])


class Replay(unittest.TestCase):
    """The 50 hand-labelled send-backs: class e (engine-only or plan gap) must no longer reach the writer as a gap, a-d must."""

    def test_report(self):
        out = {}
        for r in SENDBACKS:
            routed = fnd.route([r["said"]], [], Ledger(None, []))
            out.setdefault(r["class"], []).append(bool(routed.unmet))
        report = {k: f"{sum(v)}/{len(v)} still sent back" for k, v in sorted(out.items())}
        print("replay of the 50 labelled send-backs:", report)
        self.assertEqual(len(SENDBACKS), 50)
        # the bd-filing rows of class e (#32 #33 #35 #44) are filed by the engine; no real defect (a) is dropped as a bd demand
        for r in SENDBACKS:
            if r["n"] in (32, 33, 35, 44):
                self.assertEqual(fnd.route([r["said"]], [], Ledger(None, [])).unmet, [], r["said"])
            if r["class"] == "a":
                self.assertEqual(fnd.route([r["said"]], [], Ledger(None, [])).unmet, [r["said"]], r["said"])


if __name__ == "__main__":
    unittest.main()
