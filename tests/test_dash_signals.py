"""The Roadmap's signal strip: each rule fires on the shape it was made for and stays quiet on ordinary data."""

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
import signals  # noqa: E402

NOW = 1_800_000_000.0
H = 3600


def row(i, fresh=100_000, cached=0, **kw):
    r = {"id": "r-" + i, "state": "stopped", "updated": NOW - H, "runs": 1, "blocks": 4, "secs": 1000, "red_checks": 0,
         "replans": 0, "checks_secs": 0, "tokens_all": {"in": fresh + cached, "cached": cached, "out": 0}}
    r.update(kw)
    return r


def pas(i, outcome="parked", ago=H, why="", minutes=30):
    return {"id": "r-" + i, "outcome": outcome, "t": NOW - ago, "minutes": minutes, "why": why}


def kinds(sigs):
    return [s["kind"] for s in sigs["signals"]]


def build(rows=(), passes=(), lanes=(), asks=(), summary=None):
    return signals.build(list(rows), list(passes), list(lanes), list(asks), summary, NOW)


class Quiet(unittest.TestCase):
    def test_ordinary_data_fires_nothing_but_good_news(self):
        rows = [row(str(i), fresh=100_000 + i * 1000) for i in range(10)]
        passes = [pas("a", "landed", minutes=20), pas("b", "parked", why="needs a human: spike"), pas("c", "parked", why="needs a human: x")]
        self.assertEqual(kinds(build(rows, passes)), ["good"])


class Lanes(unittest.TestCase):
    def test_out_lane_is_red_with_the_wait_and_a_short_reason(self):
        s = build(lanes=[{"name": "CLAUDE_SUBSCRIPTION", "out_until": NOW + 3 * H + 600, "why": "usage limit reached: resets later (https://x)"}])
        (x,) = s["signals"]
        self.assertEqual((x["sev"], x["title"]), ("red", "Claude lane out"))
        self.assertIn("3h10m", x["line"])
        self.assertNotIn("resets later", x["line"])

    def test_a_credit_lane_out_is_no_alarm_unattended_runs_never_use_it(self):
        s = build(lanes=[{"name": "CLAUDE_CREDIT", "out_until": NOW + 3 * H, "why": "credit balance too low"},
                         {"name": "claude_credit", "usage": [{"window": "5h", "used_pct": 99.0, "resets_at": NOW + H}]}])
        self.assertEqual(s["signals"], [])

    def test_a_lane_that_is_back_and_low_usage_is_quiet_high_usage_is_amber(self):
        quiet = [{"name": "OPENAI_SUBSCRIPTION", "out_until": NOW - 5, "usage": [{"window": "5h", "used_pct": 40.0, "resets_at": NOW + H}]}]
        self.assertEqual(kinds(build(lanes=quiet)), [])
        high = [{"name": "OPENAI_SUBSCRIPTION", "usage": [{"window": "5h", "used_pct": 97.0, "resets_at": NOW + H}]}]
        (x,) = build(lanes=high)["signals"]
        self.assertEqual((x["kind"], x["sev"]), ("lane_high", "amber"))


class ParkCluster(unittest.TestCase):
    WHY = "needs a human: delegate stopped the write step (bad_request): codex rejected the request: {\"type\":\"error\"}"

    def test_one_cause_in_a_burst_is_red(self):
        passes = [pas(str(i), why=self.WHY, ago=H + i * 600) for i in range(5)]
        (x,) = [s for s in build(passes=passes)["signals"] if s["kind"] == "park_cluster"]
        self.assertEqual(x["sev"], "red")
        self.assertIn("delegate stopped the write step", x["line"])
        self.assertNotIn("{", x["line"])

    def test_different_causes_or_old_parks_do_not_cluster(self):
        mixed = [pas(str(i), why="needs a human: reason %s" % "abcdef"[i]) for i in range(5)]
        self.assertNotIn("park_cluster", kinds(build(passes=mixed)))
        old = [pas(str(i), why=self.WHY, ago=20 * H) for i in range(6)]
        self.assertNotIn("park_cluster", kinds(build(passes=old)))

    def test_cause_normalises_ids_numbers_and_payloads(self):
        a = signals.cause("over budget: $0.00 of $15, 182 of 180 min (182 min wall)")
        b = signals.cause("over budget: $0.00 of $15, 187 of 180 min (180 min wall)")
        self.assertEqual(a, b)
        self.assertEqual(signals.cause("the check before land: nothing proves lifesim-d5f.34 {\"x\": 1}"),
                         "the check before land: nothing proves")


class Churn(unittest.TestCase):
    def test_checks_failing_repeatedly_names_the_bead_and_the_share_of_time(self):
        rows = [row("a", red_checks=6, blocks=22, secs=1000, checks_secs=600), row("b", red_checks=1)]
        (x,) = [s for s in build(rows)["signals"] if s["kind"] == "churn"]
        self.assertEqual((x["look"], x["sev"]), (["r-a"], "amber"))
        self.assertIn("checks failed 6×", x["line"])
        self.assertIn("60% of its time in checks", x["line"])

    def test_landed_or_stale_beads_and_plain_step_counts_below_the_bar_are_quiet(self):
        rows = [row("a", red_checks=9, state="landed"), row("b", red_checks=9, updated=NOW - 3 * 86400), row("c", blocks=11)]
        self.assertNotIn("churn", kinds(build(rows)))

    def test_many_steps_alone_fire_and_replans_say_the_plan_is_wrong(self):
        self.assertIn("churn", kinds(build([row("a", blocks=14)])))
        (x,) = [s for s in build([row("a", replans=3)])["signals"] if s["kind"] == "churn"]
        self.assertIn("the plan, not the code", x["line"])


class Rounds(unittest.TestCase):
    def test_sendbacks_slow_checks_and_a_huge_write_turn(self):
        s = build([row("a", sendbacks=2), row("b", red_checks=2, longest_check=660), row("c", big_turn=12_300_000)])
        by = {x["kind"]: x for x in s["signals"] if x["kind"] in ("churn", "big_turn")}
        self.assertEqual(sorted(x["look"][0] for x in s["signals"] if x["kind"] == "churn"), ["r-a", "r-b"])
        self.assertIn("review sent it back 2×", [x for x in s["signals"] if x["look"] == ["r-a"]][0]["line"])
        self.assertIn("up to 11m", [x for x in s["signals"] if x["look"] == ["r-b"]][0]["line"])
        self.assertIn("12.3M", by["big_turn"]["title"])

    def test_one_slow_check_round_alone_is_quiet(self):
        self.assertNotIn("churn", kinds(build([row("a", red_checks=1, longest_check=900)])))


class Tokens(unittest.TestCase):
    def test_a_hog_is_judged_on_fresh_tokens_not_cache(self):
        rows = [row(str(i), fresh=100_000) for i in range(10)] + [row("hog", fresh=900_000, cached=20_000_000),
                                                                  row("cached", fresh=100_000, cached=30_000_000)]
        s = build(rows)
        (x,) = [t for t in s["signals"] if t["kind"] == "token_hog"]
        self.assertEqual(x["look"], ["r-hog"])
        self.assertIn("900k fresh", x["title"])
        self.assertIn("20.9M with cache", x["line"])
        self.assertEqual(s["stats"]["median_fresh"], 100_000)

    def test_nothing_above_the_floor_is_quiet(self):
        self.assertNotIn("token_hog", kinds(build([row(str(i), fresh=300_000) for i in range(6)])))


class Asks(unittest.TestCase):
    def ask(self, i, age, kind="stuck", parks_in=72 * H):
        return {"bead": "r-" + i, "kind": kind, "t": NOW - age, "parks_at": NOW - age + parks_in, "status": "open"}

    def test_fresh_asks_are_info_old_amber_very_old_or_parking_red(self):
        sev = lambda asks: [s["sev"] for s in build(asks=asks)["signals"] if s["kind"] == "asks"]
        self.assertEqual(sev([self.ask("a", H)]), ["info"])
        self.assertEqual(sev([self.ask("a", 13 * H)]), ["amber"])
        self.assertEqual(sev([self.ask("a", 25 * H)]), ["red"])
        self.assertEqual(sev([self.ask("a", 13 * H, parks_in=20 * H)]), ["red"])

    def test_groups_by_kind_and_names_the_oldest_first_and_skips_answered(self):
        asks = [self.ask("a", 30 * H), self.ask("b", 2 * H, "verify"), dict(self.ask("c", 50 * H), answer="x", answered_here=True)]
        (x,) = [s for s in build(asks=asks)["signals"] if s["kind"] == "asks"]
        self.assertEqual(x["look"], ["r-a", "r-b"])
        self.assertIn("1 stuck, 1 verify", x["line"])
        self.assertEqual(x["href"], "#asks")


class OthersAndGood(unittest.TestCase):
    def test_budget_near_miss_and_stuck_beads(self):
        near = pas("a", why="over budget: $0.00 of $15, 182 of 180 min (182 min wall)", ago=H)
        far = pas("b", why="over budget: $0.00 of $15, 400 of 180 min", ago=H)
        s = build(passes=[near, far], summary={"stuck": 2})
        (x,) = [t for t in s["signals"] if t["kind"] == "near_miss"]
        self.assertEqual((x["look"], x["sev"]), (["r-a"], "info"))
        self.assertIn("182/180 min", x["line"])
        tricky = pas("c", why="over budget: $0.00 of $15, 90 of 100 min wall, 182 of 180 min", ago=H)  # the first match wins, in both places
        (y,) = [t for t in build(passes=[tricky])["signals"] if t["kind"] == "near_miss"]
        self.assertIn("90/100 min", y["line"])
        self.assertEqual([t["sev"] for t in s["signals"] if t["kind"] == "stuck"], ["red"])

    def test_good_news_counts_landings_and_first_run_share(self):
        passes = [pas("a", "landed", minutes=10), pas("b", "landed", minutes=30), pas("c", "landed", ago=30 * H)]
        rows = [row("a", state="landed"), row("b", state="landed", runs=2)]
        (x,) = build(rows, passes)["signals"]
        self.assertEqual((x["kind"], x["sev"], x["title"]), ("good", "green", "2 landed in 24 h"))
        self.assertIn("median 20m", x["line"])
        self.assertIn("1 of 2 finished beads", x["line"])

    def test_order_is_red_amber_info_green(self):
        s = build([row("a", red_checks=4)], [pas("a", "landed")], [{"name": "CLAUDE", "out_until": NOW + H}], [])
        self.assertEqual([x["sev"] for x in s["signals"]], ["red", "amber", "green"])


if __name__ == "__main__":
    unittest.main()
