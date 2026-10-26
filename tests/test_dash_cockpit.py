"""tl-7y6.3.1 stage 1: delegate_status() carries every lane's cockpit data, fresh on every refresh, and only ever
invokes `route.py status --json`. All of delegate is mocked: no vendor is reached, nothing is written."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import server  # noqa: E402

ROUTE = "/x/iorlas-delegate/0.35.1/skills/delegate/route.py"


def lane(**kw):
    return dict({"family": "claude", "kind": "subscription", "out": False, "out_until": None, "notes": []}, **kw)


class Cockpit(unittest.TestCase):
    def status(self, j, **res):
        """delegate_status() with route.py mocked to this answer (extra CompletedProcess fields via res)."""
        ret = dict({"stdout": json.dumps(j), "returncode": 0, "stderr": ""}, **res)
        with mock.patch.object(server.glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(server.subprocess, "run", return_value=mock.Mock(**ret)) as run:
            d = server.delegate_status()
        return d, run

    def test_every_lane_is_listed_with_its_cockpit_fields(self):
        j = {"v": 1, "lanes": {
            "OPENAI_SUBSCRIPTION": lane(family="openai", out=True, out_until=1793104732, reason="limit",
                                        model="gpt-5.2-codex", usage=[{"window": "5h", "used_pct": 78,
                                                                       "resets_at": 1793104732}]),
            "CLAUDE_SUBSCRIPTION": lane(model="sonnet-4.6", five=41, week=6)}}
        d, _ = self.status(j)
        rows = d["lanes"]
        self.assertEqual([r["name"] for r in rows], ["OPENAI_SUBSCRIPTION", "CLAUDE_SUBSCRIPTION"])  # delegate's order
        self.assertEqual(rows[0]["model"], "gpt-5.2-codex")
        self.assertEqual(rows[0]["reason"], "limit")
        self.assertTrue(rows[0]["out"])
        self.assertEqual(rows[0]["out_until"], 1793104732)
        self.assertEqual(rows[0]["usage"], [{"window": "5h", "used_pct": 78, "resets_at": 1793104732}])
        self.assertFalse(rows[1]["out"])
        self.assertIsNone(rows[1]["out_until"])
        self.assertEqual(rows[1]["usage"], [{"window": "5h", "used_pct": 41}, {"window": "week", "used_pct": 6}])

    def test_a_lane_that_said_no_model_unlock_or_usage_keeps_them_empty(self):
        d, _ = self.status({"v": 1, "lanes": {"CLAUDE_CREDIT": lane(kind="credit", out=True)}})
        r = d["lanes"][0]
        self.assertIsNone(r["model"])  # never invented
        self.assertIsNone(r["out_until"])
        self.assertEqual(r["usage"], [])
        self.assertEqual(r["notes"], [])

    def test_usage_windows_with_unknown_percentages_keep_their_reset_times(self):
        j = {"v": 1, "lanes": {"A": lane(usage=[{"window": "5h", "used_pct": "half"}, {"window": "week"},
                                                 {"window": "month", "used_pct": None, "resets_at": 1793104732},
                                                 "junk"], five=41)}}
        d, _ = self.status(j)
        self.assertEqual(d["lanes"][0]["usage"], [
            {"window": "5h", "used_pct": None, "resets_at": None},
            {"window": "week", "used_pct": None, "resets_at": None},
            {"window": "month", "used_pct": None, "resets_at": 1793104732}])

    def test_week_with_null_usage_preserves_its_reset_time(self):
        window = {"window": "week", "used_pct": None, "resets_at": 1793104732}
        d, _ = self.status({"lanes": {"A": lane(usage=[window])}})
        self.assertEqual(d["lanes"][0]["usage"], [window])

    def test_the_banner_fields_out_detail_and_needs_input_are_still_there(self):
        j = {"v": 1, "needs_input": ["OPENAI_SUBSCRIPTION"], "lanes": {
            "CLAUDE_SUBSCRIPTION": lane(out=True, notes=["claude is logged out: run `claude auth login`"]),
            "CLAUDE_CREDIT": lane(kind="credit", out=True)}}
        d, _ = self.status(j)
        self.assertFalse(d["ok"])
        self.assertEqual(d["out"], ["CLAUDE_SUBSCRIPTION"])  # the credit lane earns no banner, as before
        self.assertEqual(d["detail"]["CLAUDE_SUBSCRIPTION"]["text"], "Claude logged out: run claude auth login")
        self.assertEqual(d["needs_input"], ["OPENAI_SUBSCRIPTION"])

    def test_lanes_named_agent_runs_style_list_are_read_too(self):
        j = {"v": 1, "lanes": [{"name": "OPENAI_SUBSCRIPTION", "family": "openai", "out": True, "out_until": 1793104732,
                                "why": "limit refusal"}]}
        d, _ = self.status(j)
        self.assertEqual([r["name"] for r in d["lanes"]], ["OPENAI_SUBSCRIPTION"])
        self.assertEqual(d["out"], ["OPENAI_SUBSCRIPTION"])
        self.assertTrue(d["lanes"][0]["out"])

    def test_the_only_invocation_is_status_json(self):
        d, run = self.status({"v": 1, "lanes": {"CLAUDE_SUBSCRIPTION": lane()}})
        self.assertTrue(d["ok"])
        self.assertEqual(run.call_args[0][0],
                         [sys.executable, ROUTE, "status", "--json"])  # reporting only: no quota is ever spent

    def test_supplied_emoji_and_list_style_reason_are_preserved(self):
        d, _ = self.status({"lanes": [{"name": "A", "emoji": "🟠", "why": "limit refusal", "out": True}]})
        self.assertEqual(d["lanes"][0]["emoji"], "🟠")
        self.assertEqual(d["lanes"][0]["reason"], "limit refusal")

    def test_missing_lane_state_stays_unknown(self):
        d, _ = self.status({"lanes": {"A": {}}})
        self.assertIsNone(d["lanes"][0]["out"])

    def test_legacy_usage_does_not_duplicate_an_explicit_window(self):
        d, _ = self.status({"lanes": {"A": lane(five=41, week=6,
                                               usage=[{"window": "5h", "used_pct": 78}])}})
        self.assertEqual([(u["window"], u["used_pct"]) for u in d["lanes"][0]["usage"]],
                         [("5h", 78), ("week", 6)])

    def test_non_list_usage_and_nonfinite_percentages_do_not_break_status(self):
        for usage in (42, [{"window": "5h", "used_pct": float("nan")},
                           {"window": "week", "used_pct": float("inf")}],
                      [{"window": "5h", "used_pct": True}]):
            with self.subTest(usage=usage):
                d, _ = self.status({"lanes": {"A": lane(usage=usage)}})
                self.assertTrue(d["ok"])
                self.assertEqual(d["lanes"][0]["usage"],
                                 [{"window": u["window"], "used_pct": None, "resets_at": None}
                                  for u in usage] if isinstance(usage, list) else [])


class Fresh(unittest.TestCase):
    """No 60-second cache: what delegate says now is what the next refresh shows (tl-7y6.3.1)."""

    def answer(self, lanes):
        return mock.Mock(stdout=json.dumps({"v": 1, "lanes": lanes}), returncode=0, stderr="")

    def patched(self):
        return [mock.patch.object(server.glob, "glob", return_value=[ROUTE]),
                mock.patch.object(server.subprocess, "run")]

    def test_a_lane_that_went_out_shows_on_the_next_call(self):
        fixes = self.patched()
        with fixes[0], fixes[1] as run:
            run.side_effect = [self.answer({"A": lane()}), self.answer({"A": lane(out=True, out_until=1793104732)})]
            self.assertTrue(server.delegate_status()["ok"])
            d2 = server.delegate_status()  # no wait, no cache to clear
        self.assertFalse(d2["ok"])
        self.assertEqual(d2["out"], ["A"])
        self.assertTrue(d2["lanes"][0]["out"])
        self.assertEqual(run.call_count, 2)  # every refresh asks again

    def test_a_lane_that_came_back_shows_on_the_next_call(self):
        fixes = self.patched()
        with fixes[0], fixes[1] as run:
            run.side_effect = [self.answer({"A": lane(out=True)}), self.answer({"A": lane()})]
            self.assertFalse(server.delegate_status()["ok"])
            d2 = server.delegate_status()
        self.assertTrue(d2["ok"])
        self.assertEqual(d2["lanes"][0]["out"], False)


class Unavailable(unittest.TestCase):
    def test_no_delegate_installed_says_so_and_runs_nothing(self):
        with mock.patch.object(server.glob, "glob", return_value=[]), \
                mock.patch.object(server.subprocess, "run") as run:
            d = server.delegate_status()
        self.assertFalse(d["ok"])
        self.assertEqual(d["say"], "delegate is not installed")
        self.assertNotIn("lanes", d)
        run.assert_not_called()

    def test_a_route_that_never_answers_is_said(self):
        with mock.patch.object(server.glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(server.subprocess, "run", side_effect=OSError("no such file")):
            d = server.delegate_status()
        self.assertFalse(d["ok"])
        self.assertIn("failed", d["say"])
        self.assertNotIn("lanes", d)

    def test_timeout_is_reported_without_retrying_or_serving_old_lanes(self):
        with mock.patch.object(server.glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(server.subprocess, "run", side_effect=server.subprocess.TimeoutExpired(
                    [sys.executable, ROUTE, "status", "--json"], 20)) as run:
            d = server.delegate_status()
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
        for lanes in ({}, []):
            d, _ = Cockpit().status({"lanes": lanes})
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
        with mock.patch.object(server.glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(server.subprocess, "run",
                                  return_value=mock.Mock(stdout="", stderr="boom\ncannot read state", returncode=3)):
            d = server.delegate_status()
        self.assertFalse(d["ok"])
        self.assertEqual(d["say"], "delegate status exited 3: cannot read state")
        self.assertNotIn("lanes", d)

    def test_garbage_output_is_said_as_malformed(self):
        for out in ("", "not json at all"):
            with mock.patch.object(server.glob, "glob", return_value=[ROUTE]), \
                    mock.patch.object(server.subprocess, "run",
                                      return_value=mock.Mock(stdout=out, stderr="", returncode=0)):
                d = server.delegate_status()
            self.assertFalse(d["ok"])
            self.assertEqual(d["say"], "delegate status printed no JSON status")
            self.assertNotIn("lanes", d)

    def test_notes_before_the_object_are_tolerated(self):
        body = json.dumps({"v": 1, "lanes": {"A": lane(model="sonnet-4.6")}})
        with mock.patch.object(server.glob, "glob", return_value=[ROUTE]), \
                mock.patch.object(server.subprocess, "run",
                                  return_value=mock.Mock(stdout="warning: cache is cold\n" + body, stderr="",
                                                         returncode=0)):
            d = server.delegate_status()
        self.assertTrue(d["ok"])
        self.assertEqual(d["lanes"][0]["model"], "sonnet-4.6")


if __name__ == "__main__":
    unittest.main()
