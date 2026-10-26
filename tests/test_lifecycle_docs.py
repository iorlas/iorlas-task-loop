"""The frozen baseline and the metric names in docs/study/README.md match what the code produces."""
import io
import json
import re
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import lifecycle  # noqa: E402
import report  # noqa: E402

BASELINE = json.loads((ROOT / "docs" / "study" / "baselines-2026-10-25.json").read_text(encoding="utf-8"))
REQUIRED = ["landed_beads_per_day", "slot_min_per_landed_bead", "non_landing_slot_min_share", "avoidable_asks",
            "beads_landed_on_run_1", "runs_per_landed_bead", "median_dead_time_per_started_because", "fingerprints",
            "fingerprint_streaks", "slot_min_over_180", "verify_stage_slot_min", "hung_step_slot_min",
            "median_release_gate_min", "uncached_input_tokens_per_landed_bead", "reverts_per_100_landings",
            "quota_percent_per_landed_bead"]


def lines_of(r):
    out = io.StringIO()
    with redirect_stdout(out):
        report.print_lifecycle(r)
    return out.getvalue()


class Baseline(unittest.TestCase):
    def test_it_names_engine_sha_window_and_scope(self):
        e = BASELINE["engine"]
        self.assertTrue(re.fullmatch(r"\d+\.\d+\.\d+", e["version"]))
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", e["source_sha"]))
        self.assertTrue(BASELINE["window"]["since"] < BASELINE["window"]["until"])
        self.assertIn("lifesim", BASELINE["scope"]["repo"])

    def test_every_metric_is_a_number_or_listed_unavailable_with_a_reason(self):
        listed = {u["metric"] for u in BASELINE["unavailable"]}
        for u in BASELINE["unavailable"]:
            self.assertTrue(u["reason"])
        for k in REQUIRED:
            self.assertIn(k, BASELINE["metrics"], k)
            v = BASELINE["metrics"][k]
            if v is None or v == "unavailable":
                self.assertIn(k, listed, k)

    def test_corrections_are_exactly_the_study_figures_more_than_ten_percent_off(self):
        got = {c["metric"] for c in BASELINE["corrections"] if not c["metric"].startswith("median_dead_time")}
        want = {k for k, s in BASELINE["study_figures"].items()
                if BASELINE["metrics"].get(k) is not None and abs(BASELINE["metrics"][k] - s) / s > 0.10}
        self.assertEqual(got, want)

    def test_the_study_snapshot_reproduces_the_stage_figures_within_two_percent(self):
        s = BASELINE["snapshot_at_study"]["metrics"]
        for k, study in (("landed_beads", 131), ("slot_min", 17541), ("non_landing_slot_min", 9774)):
            self.assertAlmostEqual(s[k], study, delta=study * 0.02, msg=k)

    def test_cache_table_lists_runs_with_paths_and_hit_miss_counts(self):
        t = BASELINE["cache_hit_table"]
        self.assertTrue(t["available"])
        self.assertTrue(t["runs"])
        for r in t["runs"]:
            self.assertTrue(r["changed_paths"])
        self.assertEqual(t["hit"] + t["miss"], sum(x["hit"] + x["miss"] for r in t["runs"] if isinstance(r["rounds"], list)
                                                  for x in r["rounds"]))


class Readme(unittest.TestCase):
    def test_every_metric_name_in_the_readme_is_a_line_the_cli_prints(self):
        text = (ROOT / "docs" / "study" / "README.md").read_text(encoding="utf-8")
        names = re.findall(r"^\| `([^`]+)` \|", text, re.M)
        self.assertEqual(len(names), 16)
        w = lifecycle.lifecycle_report([], since=0, until=lifecycle.WEEK)
        printed = lines_of(w)
        for n in names:
            self.assertRegex(printed, r"(?m)^  " + re.escape(n) + r"( \(min\))?:", n)


if __name__ == "__main__":
    unittest.main()
