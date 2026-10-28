"""tl-7y6.3.1 stage 1: delegate_status() carries every lane's cockpit data, fresh on every refresh, and only ever
invokes `route.py status --json`. All of delegate is mocked: no vendor is reached, nothing is written."""
import glob
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

DASH = make_dash()

ROUTE = "/x/iorlas-delegate/0.35.1/skills/delegate/route.py"


FIX = ROOT / "tests" / "fixtures"
REAL = json.loads((FIX / "delegate_status_0.48.1_real.json").read_text())
FULL = json.loads((FIX / "delegate_status_0.48_full.json").read_text())


def lane(**kw):
    return dict({"family": "claude", "kind": "subscription", "out": False, "out_until": None, "notes": []}, **kw)


def answer(j):
    """A typed 0.48 answer for these top-level lanes, with one cockpit row each."""
    rows = [{"id": n, "state": "resting" if ln.get("out") else "ready", "model": ln.get("model")} for n, ln in j["lanes"].items()] if isinstance(j["lanes"], dict) else []
    return dict(j, cockpit={"v": 1, "lanes": rows})


class Cockpit(unittest.TestCase):
    def status(self, j, **res):
        """delegate_status() with route.py mocked to this answer (extra CompletedProcess fields via res)."""
        ret = dict({"stdout": json.dumps(j), "returncode": 0, "stderr": ""}, **res)
        with mock.patch.object(glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(subprocess, "run", return_value=mock.Mock(**ret)) as run:
            d = DASH.lanes.delegate_status()
        return d, run

    def test_full_fixture_fills_every_card_field(self):
        d, _ = self.status(FULL)
        self.assertEqual([r["name"] for r in d["lanes"]], ["CLAUDE_SUBSCRIPTION", "OPENAI_SUBSCRIPTION", "GROK_SUBSCRIPTION"])
        for r, src in zip(d["lanes"], FULL["cockpit"]["lanes"]):
            with self.subTest(lane=r["name"]):
                self.assertEqual(r["model"], src["model"])
                self.assertEqual(r["reason"], src["reason"])
                self.assertEqual(r["state"], src["state"])
                self.assertEqual([(u["window"], u["used_pct"], u["resets_at"]) for u in r["usage"]],
                                 [(w["name"], w["used_pct"], w["resets_at"]) for w in src["windows"]])
                for u in r["usage"]:
                    self.assertIsNotNone(u["used_pct"])
                    self.assertIsNotNone(u["resets_at"])
        op = d["lanes"][1]
        self.assertTrue(op["out"])
        self.assertEqual(op["out_until"], FULL["cockpit"]["lanes"][1]["unlock"]["at"])
        self.assertFalse(d["lanes"][0]["out"])

    def test_real_0_48_1_answer_gives_model_reason_and_the_weekly_reset(self):
        d, _ = self.status(REAL)
        rows = {r["name"]: r for r in d["lanes"]}
        op = rows["OPENAI_SUBSCRIPTION"]
        self.assertEqual((op["model"], op["state"], op["reason"]), ("gpt-6.1-sol medium", "ready", "ready"))
        self.assertEqual(op["usage"], [{"window": "weekly", "used_pct": 9.0, "resets_at": 1793617740}])
        for r in rows.values():
            self.assertTrue(r["model"] and r["reason"] and r["state"])  # nothing for the page to render as "unknown"
        self.assertEqual(rows["CLAUDE_SUBSCRIPTION"]["state"], "unknown")  # delegate itself said so
        self.assertEqual(rows["GROK_SUBSCRIPTION"]["state"], "off")
        self.assertTrue(d["ok"])

    def test_a_cockpit_row_without_unlock_or_windows_keeps_them_empty(self):
        d, _ = self.status(answer(dict(REAL, cockpit={"v": 1, "lanes": [{"id": "A", "state": "off"}]})))
        r = d["lanes"][0]
        self.assertIsNone(r["model"])  # never invented
        self.assertIsNone(r["out_until"])
        self.assertEqual(r["usage"], [])

    def test_windows_with_unknown_percentages_keep_their_reset_times(self):
        rows = [{"id": "A", "state": "ready", "windows": [{"name": "5h", "used_pct": "half"}, {"name": "week"},
                                                          {"name": "m", "used_pct": None, "resets_at": 1793104732}, "junk"]}]
        d, _ = self.status(dict(REAL, cockpit={"v": 1, "lanes": rows}))
        self.assertEqual(d["lanes"][0]["usage"], [
            {"window": "5h", "used_pct": None, "resets_at": None},
            {"window": "week", "used_pct": None, "resets_at": None},
            {"window": "m", "used_pct": None, "resets_at": 1793104732}])

    def test_the_banner_fields_out_detail_and_needs_input_are_still_there(self):
        j = {"v": 1, "needs_input": ["OPENAI_SUBSCRIPTION"], "lanes": {
            "CLAUDE_SUBSCRIPTION": lane(out=True, notes=["claude is logged out: run `claude auth login`"]),
            "CLAUDE_CREDIT": lane(kind="credit", out=True)}}
        d, _ = self.status(answer(j))
        self.assertFalse(d["ok"])
        self.assertEqual(d["out"], ["CLAUDE_SUBSCRIPTION"])  # the credit lane earns no banner, as before
        self.assertEqual(d["detail"]["CLAUDE_SUBSCRIPTION"]["text"], "Claude logged out: run claude auth login")
        self.assertEqual(d["needs_input"], ["OPENAI_SUBSCRIPTION"])

    def test_the_only_invocation_is_status_json(self):
        d, run = self.status(answer({"v": 1, "lanes": {"CLAUDE_SUBSCRIPTION": lane()}}))
        self.assertTrue(d["ok"])
        self.assertEqual(run.call_args[0][0],
                         [sys.executable, ROUTE, "status", "--json"])  # reporting only: no quota is ever spent


class Fresh(unittest.TestCase):
    """No 60-second cache: what delegate says now is what the next refresh shows (tl-7y6.3.1)."""

    def answer(self, lanes):
        return mock.Mock(stdout=json.dumps(answer({"v": 1, "lanes": lanes})), returncode=0, stderr="")

    def patched(self):
        return [mock.patch.object(glob, "glob", return_value=[ROUTE]),
                mock.patch.object(subprocess, "run")]

    def test_a_lane_that_went_out_shows_on_the_next_call(self):
        fixes = self.patched()
        with fixes[0], fixes[1] as run:
            run.side_effect = [self.answer({"A": lane()}), self.answer({"A": lane(out=True, out_until=1793104732)})]
            self.assertTrue(DASH.lanes.delegate_status()["ok"])
            d2 = DASH.lanes.delegate_status()  # no wait, no cache to clear
        self.assertFalse(d2["ok"])
        self.assertEqual(d2["out"], ["A"])
        self.assertTrue(d2["lanes"][0]["out"])
        self.assertEqual(run.call_count, 2)  # every refresh asks again

    def test_a_lane_that_came_back_shows_on_the_next_call(self):
        fixes = self.patched()
        with fixes[0], fixes[1] as run:
            run.side_effect = [self.answer({"A": lane(out=True)}), self.answer({"A": lane()})]
            self.assertFalse(DASH.lanes.delegate_status()["ok"])
            d2 = DASH.lanes.delegate_status()
        self.assertTrue(d2["ok"])
        self.assertEqual(d2["lanes"][0]["out"], False)


class Unavailable(unittest.TestCase):
    def test_no_delegate_installed_says_so_and_runs_nothing(self):
        with mock.patch.object(glob, "glob", return_value=[]), \
                mock.patch.object(subprocess, "run") as run:
            d = DASH.lanes.delegate_status()
        self.assertFalse(d["ok"])
        self.assertEqual(d["say"], "delegate is not installed")
        self.assertNotIn("lanes", d)
        run.assert_not_called()

    def test_a_route_that_never_answers_is_said(self):
        with mock.patch.object(glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(subprocess, "run", side_effect=OSError("no such file")):
            d = DASH.lanes.delegate_status()
        self.assertFalse(d["ok"])
        self.assertIn("failed", d["say"])
        self.assertNotIn("lanes", d)

    def test_timeout_is_reported_without_retrying_or_serving_old_lanes(self):
        with mock.patch.object(glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(
                    [sys.executable, ROUTE, "status", "--json"], 20)) as run:
            d = DASH.lanes.delegate_status()
        self.assertFalse(d["ok"])
        self.assertIn("failed", d["say"])
        self.assertNotIn("lanes", d)
        run.assert_called_once()

    def test_valid_json_does_not_hide_a_nonzero_exit(self):
        d, _ = Cockpit().status({"lanes": {"A": lane()}}, returncode=2, stderr="state unavailable")
        self.assertFalse(d["ok"])
        self.assertEqual(d["say"], "delegate status exited 2: state unavailable")
        self.assertNotIn("lanes", d)

    def test_malformed_lane_shapes_are_not_reported_as_healthy(self):
        for body in ({}, {"lanes": None}, {"lanes": "broken"}, {"lanes": {"A": None}},
                     {"lanes": {"A": lane()}}, {"lanes": {"A": lane()}, "cockpit": {"lanes": "x"}},  # no cockpit rows: the 0.48 shape is required
                     {"lanes": ["A"]}, {"lanes": [{}]},
                     {"lanes": [{"name": "A"}, {"name": "A"}]},
                     {"lanes": {"A": lane(out=True, out_until="tomorrow")}},
                     {"lanes": {"A": lane(out=True, out_until=float("nan"))}},
                     {"lanes": {"A": lane(out="false")}},
                     {"lanes": {"A": lane(notes=42)}}):
            with self.subTest(body=body):
                d, _ = Cockpit().status(body)
                self.assertFalse(d["ok"])
                self.assertIn("malformed", d["say"])
                self.assertNotIn("lanes", d)

    def test_an_explicit_empty_lane_collection_is_valid(self):
        for lanes in ({},):
            d, _ = Cockpit().status(answer({"lanes": lanes}))
            self.assertTrue(d["ok"])
            self.assertEqual(d["lanes"], [])

    def test_unformattable_unlock_times_are_explicit_malformed_status_errors(self):
        for until in (1e100, -1e100):
            for out in (True, False):
                with self.subTest(until=until, out=out):
                    d, _ = Cockpit().status({"lanes": {"A": lane(out=out, out_until=until)}})
                    self.assertFalse(d["ok"])
                    self.assertIn("delegate status malformed:", d["say"])
                    self.assertNotIn("lanes", d)

    def test_a_nonzero_exit_is_said_with_its_last_word(self):
        with mock.patch.object(glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(subprocess, "run",
                                  return_value=mock.Mock(stdout="", stderr="boom\ncannot read state", returncode=3)):
            d = DASH.lanes.delegate_status()
        self.assertFalse(d["ok"])
        self.assertEqual(d["say"], "delegate status exited 3: cannot read state")
        self.assertNotIn("lanes", d)

    def test_garbage_output_is_said_as_malformed(self):
        for out in ("", "not json at all"):
            with mock.patch.object(glob, "glob", return_value=[ROUTE]), \
                    mock.patch.object(subprocess, "run",
                                      return_value=mock.Mock(stdout=out, stderr="", returncode=0)):
                d = DASH.lanes.delegate_status()
            self.assertFalse(d["ok"])
            self.assertEqual(d["say"], "delegate status printed no JSON status")
            self.assertNotIn("lanes", d)

    def test_notes_before_the_object_are_tolerated(self):
        body = json.dumps(answer({"v": 1, "lanes": {"A": lane(model="sonnet-4.6")}}))
        with mock.patch.object(glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(subprocess, "run",
                                  return_value=mock.Mock(stdout="warning: cache is cold\n" + body, stderr="",
                                                         returncode=0)):
            d = DASH.lanes.delegate_status()
        self.assertTrue(d["ok"])
        self.assertEqual(d["lanes"][0]["model"], "sonnet-4.6")


if __name__ == "__main__":
    unittest.main()
