"""The dash's lane cards and banner come from the StatusSnapshot `tl lanes` filed. The dash runs nothing: no delegate, no subprocess."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support.dashes import make_dash  # noqa: E402
from support.lanes import answer, file_status, lane  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
REAL = json.loads((FIX / "delegate_status_0.51.0_real.json").read_text())
FULL = json.loads((FIX / "delegate_status_0.48_full.json").read_text())


class Cockpit(unittest.TestCase):
    def setUp(self):
        self.dash = make_dash()

    def status(self, j, **kw):
        file_status(self.dash, j)
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("the dash ran a process")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("the dash ran a process")):
            return self.dash.lanes.delegate_status()

    def test_full_fixture_fills_every_card_field(self):
        d = self.status(dict(FULL, ts=self.dash.env.clock()))
        self.assertEqual([r["name"] for r in d["lanes"]], ["CLAUDE_SUBSCRIPTION", "OPENAI_SUBSCRIPTION", "GROK_SUBSCRIPTION"])
        for r, src in zip(d["lanes"], FULL["cockpit"]["lanes"]):
            with self.subTest(lane=r["name"]):
                self.assertEqual((r["model"], r["reason"], r["state"]), (src["model"], src["reason"], src["state"]))
                self.assertEqual([(u["window"], u["used_pct"], u["resets_at"]) for u in r["usage"]],
                                 [(w["name"], w["used_pct"], w["resets_at"]) for w in src["windows"]])
        op = d["lanes"][1]
        self.assertTrue(op["out"])
        self.assertEqual(op["out_until"], FULL["cockpit"]["lanes"][1]["unlock"]["at"])
        self.assertFalse(d["lanes"][0]["out"])
        self.assertEqual(d["needs_input"][0]["what"], "claude_usage")

    def test_real_0_51_0_answer_gives_model_reason_and_the_weekly_reset(self):
        d = self.status(dict(REAL, ts=self.dash.env.clock()))
        rows = {r["name"]: r for r in d["lanes"]}
        op = rows["OPENAI_SUBSCRIPTION"]
        self.assertEqual((op["model"], op["state"], op["reason"]), ("gpt-6.1-sol medium", "ready", "ready"))
        self.assertEqual(op["usage"], [{"window": "weekly", "used_pct": 0.0, "resets_at": 1793775376.0}])
        for r in rows.values():
            self.assertTrue(r["model"] and r["reason"] and r["state"])
        self.assertTrue(d["ok"])

    def test_windows_with_unknown_percentages_keep_their_reset_times(self):
        rows = [{"id": "A", "state": "ready", "windows": [{"name": "5h", "used_pct": "half"}, {"name": "week"},
                                                          {"name": "m", "used_pct": None, "resets_at": 1793104732}, "junk"]}]
        d = self.status(answer({"A": lane()}, cockpit={"v": 1, "lanes": rows}))
        self.assertEqual(d["lanes"][0]["usage"], [
            {"window": "5h", "used_pct": None, "resets_at": None},
            {"window": "week", "used_pct": None, "resets_at": None},
            {"window": "m", "used_pct": None, "resets_at": 1793104732.0}])

    def test_the_banner_fields_out_detail_and_needs_input(self):
        j = answer({"CLAUDE_SUBSCRIPTION": lane(out=True, notes=["claude is logged out: run `claude auth login`"]),
                    "CLAUDE_CREDIT": lane(kind="credit", out=True)},
                   needs_input=[{"what": "login", "why": "w", "how": "h"}])
        d = self.status(j)
        self.assertFalse(d["ok"])
        self.assertEqual(d["out"], ["CLAUDE_SUBSCRIPTION"])  # the credit lane earns no banner
        self.assertEqual(d["detail"]["CLAUDE_SUBSCRIPTION"]["text"], "Claude logged out: run claude auth login")
        self.assertEqual(d["needs_input"], [{"what": "login", "why": "w", "how": "h"}])

    def test_a_lane_that_went_out_shows_on_the_next_read(self):
        self.assertTrue(self.status(answer({"A": lane()}))["ok"])
        d2 = self.status(answer({"A": lane(out=True, out_until=1793104732)}))
        self.assertEqual((d2["ok"], d2["out"], d2["lanes"][0]["out"]), (False, ["A"], True))


class Unavailable(unittest.TestCase):
    def setUp(self):
        self.dash = make_dash()

    def test_no_snapshot_says_so(self):
        d = self.dash.lanes.delegate_status()
        self.assertFalse(d["ok"])
        self.assertIn("tl lanes", d["say"])

    def test_an_old_snapshot_is_said_to_be_old_never_shown_as_the_lanes(self):
        file_status(self.dash, answer({"A": lane()}, ts=self.dash.env.clock() - 7200))
        d = self.dash.lanes.delegate_status()
        self.assertFalse(d["ok"])
        self.assertIn("120 min old", d["say"])
        self.assertNotIn("lanes", d)

    def test_a_snapshot_of_another_shape_is_no_snapshot(self):
        path = self.dash.env.config.snapshot("delegate", "status")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"v": 99, "lanes": "x"}), encoding="utf-8")
        self.assertFalse(self.dash.lanes.delegate_status()["ok"])


if __name__ == "__main__":
    unittest.main()
