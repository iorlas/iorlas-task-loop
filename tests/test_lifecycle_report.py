"""tl-7y6.1.1 stage 2: the weekly lifecycle report.

The pure tests calculate every number by hand. The CLI test runs the real `tl.py report lifecycle` against an isolated
config and worktree-local traces, asks and engine logs; delegate history, quota and git follow-up are injected so the
test never reads a user's machine.
"""

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import lifecycle  # noqa: E402
import report  # noqa: E402
import tl  # noqa: E402

T0 = datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()  # Monday 00:00 UTC
H = 3600.0
DAY = 24 * H
M = 60.0


def trace(bead, outcome, start_h, end_h, why="", sha="", sessions=(), fingerprint=None, run=None,
          because="first", worktree=None):
    started, ended = T0 + start_h * H, T0 + end_h * H
    stem = run or "%s-%s" % (bead, int(started))
    return {"v": 1, "run": stem, "bead": bead, "repo": "https://example.invalid/r.git",
            "worktree": worktree, "started": started, "ended": ended, "outcome": outcome, "why": why,
            "sha": sha, "started_because": because, "fingerprint": fingerprint if fingerprint is not None else
            lifecycle.run_fingerprint(outcome, why), "sessions": list(sessions), "stats": {}}


def session(node, tin, cached, out=1):
    return {"node": node, "role": "worker", "family": "openai", "tokens": {"in": tin, "cached": cached, "out": out}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.home / "cfg"), "APPDATA": str(self.home / "cfg"),
            "CLAUDE_CODE_SESSION_ID": "abcdef12-3456", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        self.env.start()
        self.repo = self.home / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("a\n")
        git(self.repo, "add", "-A")
        commit(self.repo, "init", T0 - H)

    def tearDown(self):
        self.env.stop()

        def force(fn, path, _):
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        self.tmp.cleanup()


class Weeks(unittest.TestCase):
    def test_weeks_are_utc_monday_half_open_and_clipped(self):
        since = datetime(2026, 10, 21, 12, tzinfo=timezone.utc).timestamp()
        until = datetime(2026, 11, 3, 12, tzinfo=timezone.utc).timestamp()
        ws = lifecycle.weeks(since, until)
        self.assertEqual([x["start_iso"] for x in ws], ["2026-10-21T12:00:00Z", "2026-10-26T00:00:00Z",
                                                        "2026-11-02T00:00:00Z"])
        self.assertEqual([x["end_iso"] for x in ws], ["2026-10-26T00:00:00Z", "2026-11-02T00:00:00Z",
                                                      "2026-11-03T12:00:00Z"])
        self.assertEqual([round(x["days"], 2) for x in ws], [4.5, 7.0, 1.5])

    def test_a_boundary_is_in_the_later_week(self):
        a = trace("a", "landed", 0, 0)
        a["started"] = a["ended"] = T0 + 7 * 24 * H
        r = lifecycle.lifecycle_report([a], since=T0, until=T0 + 14 * 24 * H)
        self.assertEqual(r["weeks"][0]["landed_beads"], 0)
        self.assertEqual(r["weeks"][1]["landed_beads"], 1)

    def test_slot_min_is_clipped_at_the_week_boundary(self):
        before = trace("a", "failed", -1, 1, why="boom")
        across = trace("b", "failed", 6.5 * 24, 8 * 24, why="boom")
        r = lifecycle.lifecycle_report([before, across], since=T0, until=T0 + 14 * 24 * H)
        first, second = r["weeks"]
        # `before` starts before the window: only its hour inside the first week counts. `across` is 36 h from
        # Saturday noon: 12 h in the first week and 24 h in the second, never the whole run in both.
        self.assertEqual((first["runs"], first["slot_min"], first["slot_min_over_180"]), (1, 780.0, 720.0))
        self.assertEqual((second["runs"], second["slot_min"], second["slot_min_over_180"]), (0, 1440.0, 1440.0))
        self.assertEqual((first["non_landing_share"], second["non_landing_share"]), (1.0, 1.0))


class FixtureFiles(unittest.TestCase):
    def test_the_checked_in_fixture_reports_its_independent_numbers(self):
        d = ROOT / "tests" / "fixtures" / "lifecycle"
        r = lifecycle.lifecycle_report(report.read_jsonl(d / "traces.jsonl"), records_by_run=None,
                                       asks=report.read_jsonl(d / "asks.jsonl"),
                                       history=report.read_jsonl(d / "history.jsonl"), since=T0,
                                       until=T0 + 7 * 24 * H)
        w = r["weeks"][0]
        self.assertEqual(w["landed_beads"], 1)
        self.assertEqual(w["slot_min"], 120.0)
        self.assertEqual(w["slot_min_per_landed"], 120.0)
        self.assertEqual(w["non_landing_share"], 0.5)
        self.assertEqual((w["asks"], w["avoidable_asks"]), (2, 1))
        self.assertEqual((w["landed_run1"], w["runs_per_landed"]), (1, 2.0))
        self.assertEqual(w["fingerprints"][0]["fingerprint"], "compile error in <path>")
        self.assertEqual(w["fingerprint_streaks"][0]["max"], 2)
        self.assertEqual(w["uncached_input_per_landed"], 60.0)
        self.assertIsNone(w["reverts_per_100"])


class Core(Base):
    def setUp(self):
        super().setUp()
        self.traces = [
            trace("a", "blocked", 1, 2, why="compile error in Assets/Player.cs", because="first"),
            trace("a", "landed", 3, 3.5, sha="a" * 40, because="retry",
                  sessions=[session("write", 100, 40), session("write", 20, 5)]),
            trace("b", "landed", 2, 4, sha="b" * 40, sessions=[session("write", 50, 10)]),
            trace("c", "failed", 5, 9, why="timeout: no answer", sessions=[session("write", 200, 0)]),
            trace("d", "blocked", 6, 6 + 10 / 60, why="owner decision needed"),
        ]
        self.records = {
            "a-%d" % int(T0 + 3 * H): [
                {"t": T0 + 3.1 * H, "kind": "node", "id": 1, "step": "verify", "text": "verify"},
                {"t": T0 + 3.2 * H, "kind": "end", "id": 1, "step": "verify", "text": "verify 1: done"},
                {"t": T0 + 3.4 * H, "kind": "gate", "text": "gate: exit 0", "secs": 120, "cached": False},
            ],
            "c-%d" % int(T0 + 5 * H): [
                {"t": T0 + 8 * H, "kind": "kill", "node": "write", "why": "hung",
                 "first_error_t": T0 + 7 * H, "kill_t": T0 + 8 * H},
            ],
        }
        self.asks = [
            {"id": "a-1", "bead": "a", "kind": "verify", "why": "verify: could not check", "t": T0 + 2 * H},
            {"id": "d-1", "bead": "d", "kind": "decision", "why": "owner decision needed", "t": T0 + 3 * H},
            {"id": "c-1", "bead": "c", "kind": "stuck", "why": "over budget: $1", "t": T0 + 4 * H},
        ]
        self.history = [
            {"ts": T0 + 1 * H, "lane": "OPENAI", "model": "gpt", "status": "failed",
             "reason": "compile error in Assets/A.cs"},
            {"ts": T0 + 2 * H, "lane": "OPENAI", "model": "gpt", "status": "failed",
             "reason": "compile error in Assets/B.cs"},
            {"ts": T0 + 3 * H, "lane": "OPENAI", "model": "gpt", "status": "failed", "reason": "different"},
            {"ts": T0 + 4 * H, "lane": "OPENAI", "model": "gpt", "status": "failed",
             "reason": "compile error in Assets/C.cs"},
            {"ts": T0 + 5 * H, "lane": "OPENAI", "model": "gpt", "status": "done", "reason": ""},
        ]
        self.reverts = {
            "a-%d" % int(T0 + 3 * H): {"status": "reverted"},
            "b-%d" % int(T0 + 2 * H): {"status": "clean"},
        }
        self.quota_obs = [
            {"t": T0 + 1 * H, "lane": "OPENAI", "window": "5h", "used_pct": 10},
            {"t": T0 + 2 * H, "lane": "OPENAI", "window": "5h", "used_pct": 30},
        ]

    def card(self, **kw):
        return lifecycle.lifecycle_report(self.traces, records_by_run=self.records, asks=self.asks,
                                          history=self.history, since=T0, until=T0 + 7 * 24 * H,
                                          reverts=self.reverts, quota_observations=self.quota_obs, **kw)

    def test_every_weekly_number_is_independently_reproduced(self):
        w = self.card()["weeks"][0]
        self.assertEqual(w["landed_beads"], 2)
        self.assertEqual(w["landed_beads_per_day"], round(2 / 7, 2))
        self.assertEqual(w["slot_min"], 460.0)          # 60 + 30 + 120 + 240 + 10
        self.assertEqual(w["slot_min_per_landed"], 230.0)
        self.assertEqual(w["non_landing_slot_min"], 310.0)
        self.assertEqual(w["non_landing_share"], round(310 / 460, 4))
        self.assertEqual((w["avoidable_asks"], w["asks"]), (2, 3))
        self.assertEqual((w["landed_run1"], w["landed_run1_share"]), (1, 0.5))
        self.assertEqual((w["runs"], w["runs_per_landed"]), (5, 2.5))
        self.assertEqual(w["dead_time_min"]["retry"], 60.0)
        self.assertEqual(w["slot_min_over_180"], 240.0)
        self.assertEqual(w["verify_slot_min"], 6.0)
        self.assertEqual(w["hung_slot_min"], 60.0)
        self.assertEqual(w["release_gate_median_min"], 2.0)
        self.assertEqual(w["uncached_input"], 315)     # a: 60+15, b: 40, c: 200
        self.assertEqual(w["uncached_input_per_landed"], 157.5)
        self.assertEqual((w["reverts"], w["fixed_forward"], w["revert_eligible"]), (1, 0, 2))
        self.assertEqual(w["reverts_per_100"], 50.0)
        self.assertEqual(w["quota_pct_per_landed"], 10.0)

    def test_fingerprints_and_streaks_are_grouped_and_ranked(self):
        w = self.card()["weeks"][0]
        self.assertEqual(w["fingerprints"][0]["fingerprint"], "compile error in <path>")
        self.assertEqual(w["fingerprints"][0]["beads"], 1)
        self.assertEqual(w["fingerprints"][0]["per_day"], round(1 / 7, 2))
        self.assertEqual(w["fingerprint_streaks"], [
            {"lane": "OPENAI", "model": "gpt", "fingerprint": "compile error in <path>", "max": 2}])

    def test_a_missing_reason_breaks_a_streak(self):
        hist = [
            {"ts": T0 + 1 * H, "lane": "L", "model": "m", "status": "failed", "reason": "compile error in Assets/A.cs"},
            {"ts": T0 + 2 * H, "lane": "L", "model": "m", "status": "failed", "reason": ""},
            {"ts": T0 + 3 * H, "lane": "L", "model": "m", "status": "failed", "reason": "compile error in Assets/B.cs"},
            {"ts": T0 + 4 * H, "lane": "L", "model": "m", "status": "failed", "reason": "compile error in Assets/C.cs"},
        ]
        w = lifecycle.lifecycle_report([], records_by_run={}, asks=[], history=hist, since=T0,
                                       until=T0 + 7 * 24 * H)["weeks"][0]
        # Without the empty-reason row breaking it, A/B/C would be a streak of three.
        self.assertEqual(w["fingerprint_streaks"], [
            {"lane": "L", "model": "m", "fingerprint": "compile error in <path>", "max": 2}])

    def test_cached_release_gates_do_not_enter_the_median(self):
        recs = {k: list(v) for k, v in self.records.items()}
        key = "a-%d" % int(T0 + 3 * H)
        recs[key].append({"t": T0 + 3.5 * H, "kind": "gate", "secs": 600, "cached": True})
        w = lifecycle.lifecycle_report(self.traces, records_by_run=recs, asks=self.asks, history=self.history,
                                       since=T0, until=T0 + 7 * 24 * H, reverts=self.reverts,
                                       quota_observations=self.quota_obs)["weeks"][0]
        self.assertEqual((w["release_gate_median_min"], w["release_gates"]), (2.0, 1))

    def test_done_is_non_landing_and_runs_per_landed_uses_every_run(self):
        rows = [trace("a", "done", 1, 2, why="", sessions=[session("write", 10, 0)]),
                trace("a", "landed", 3, 4, sha="a" * 40, sessions=[session("write", 20, 0)]),
                trace("b", "failed", 5, 6, why="boom", sessions=[session("write", 30, 0)])]
        w = lifecycle.lifecycle_report(rows, since=T0, until=T0 + 7 * 24 * H)["weeks"][0]
        self.assertEqual((w["landed_beads"], w["runs"], w["runs_per_landed"]), (1, 3, 3.0))
        self.assertEqual((w["non_landing_slot_min"], w["slot_min"]), (120.0, 180.0))
        self.assertEqual(w["uncached_input"], 60)

    def test_duplicate_landings_count_one_bead_and_the_first_run(self):
        dup = trace("b", "landed", 5, 6, sha="b" * 40, because="resume")
        r = lifecycle.lifecycle_report(self.traces + [dup], records_by_run=self.records, asks=self.asks,
                                       history=self.history, since=T0, until=T0 + 7 * 24 * H,
                                       reverts=self.reverts, quota_observations=self.quota_obs)
        w = r["weeks"][0]
        self.assertEqual(w["landed_beads"], 2)
        self.assertEqual(w["runs"], 6)
        self.assertEqual(w["revert_eligible"], 2)

    def test_missing_endpoints_and_missing_sources_are_unavailable_not_zero(self):
        bad = [{"bead": "x", "run": "x-1", "started": T0 + 1 * H, "outcome": "failed", "why": "boom"},
               {"bead": "y", "run": "y-1", "started": T0 + 2 * H, "ended": T0 + 2.5 * H, "outcome": "landed"}]
        r = lifecycle.lifecycle_report(bad, records_by_run=None, asks=[], history=None, since=T0,
                                       until=T0 + 7 * 24 * H)
        w = r["weeks"][0]
        self.assertIsNone(w["non_landing_share"])
        self.assertIsNone(w["verify_slot_min"])
        self.assertIsNone(w["hung_slot_min"])
        self.assertIsNone(w["fingerprint_streaks"])
        self.assertIn("slot-min", w["unavailable"])
        self.assertIn("verify-stage-slot-min", w["unavailable"])

    def test_legacy_and_malformed_rows_do_not_crash(self):
        rows = [None, {}, {"bead": "z", "started": "nope", "outcome": "blocked", "why": "boom"},
                {"bead": "z", "started": T0, "ended": "x", "outcome": "landed"},
                trace("z", "landed", 1, 2, sha="z" * 40)]
        r = lifecycle.lifecycle_report(rows, records_by_run={}, asks=[{}], history=[], since=T0,
                                       until=T0 + 7 * 24 * H)
        self.assertEqual(r["weeks"][0]["landed_beads"], 1)

    def test_zero_landings_documents_the_denominators(self):
        rows = [trace("a", "blocked", 1, 2, why="boom")]
        w = lifecycle.lifecycle_report(rows, records_by_run={}, asks=[], history=[], since=T0,
                                       until=T0 + 7 * 24 * H)["weeks"][0]
        self.assertEqual(w["landed_beads"], 0)
        self.assertIsNone(w["slot_min_per_landed"])
        self.assertIsNone(w["runs_per_landed"])
        self.assertIsNone(w["landed_run1_share"])
        self.assertIsNone(w["reverts_per_100"])
        self.assertIn("slot-min-per-landed", w["unavailable"])

    def test_one_quota_snapshot_is_not_a_week_of_consumption(self):
        w = lifecycle.lifecycle_report(self.traces, records_by_run=self.records, asks=self.asks,
                                       history=self.history, since=T0, until=T0 + 7 * 24 * H,
                                       reverts=self.reverts, quota_observations=[],
                                       quota={"available": True, "lanes": []})["weeks"][0]
        self.assertIsNone(w["quota_pct_per_landed"])
        self.assertIn("quota-percent-per-landed", w["unavailable"])

    def test_missing_history_is_unavailable_but_an_empty_file_is_an_empty_history(self):
        p = self.home / "history.jsonl"
        self.assertEqual(report.history_rows(p), (None, False))
        p.write_text("")
        self.assertEqual(report.history_rows(p), ([], True))

    def test_quota_snapshot_reads_the_status_lane_shape(self):
        snap = report.quota_snapshot(lanes={"OPENAI": {"out": False, "usage": [
            {"window": "5h", "used_pct": 30, "resets_at": 0}]}}, now=T0)
        self.assertTrue(snap["available"])
        self.assertEqual((snap["lanes"][0]["lane"], snap["lanes"][0]["used_pct"]), ("OPENAI", 30))

    def test_quota_snapshot_reads_the_five_and_week_percentages_delegate_prints_today(self):
        snap = report.quota_snapshot(lanes={"OPENAI": {"out": False, "five": None, "week": 2.0},
                                            "CLAUDE": {"out": True, "five": None, "week": None}}, now=T0)
        self.assertEqual([(x["lane"], x["window"], x["used_pct"]) for x in snap["lanes"]], [("OPENAI", "week", 2.0)])

    def test_whole_window_is_one_bucket_not_split_at_the_utc_monday(self):
        ws = lifecycle.weeks(T0 - 2 * DAY, T0 + 9 * DAY, whole=True)
        self.assertEqual(len(ws), 1)
        self.assertEqual((ws[0]["start"], ws[0]["end"]), (T0 - 2 * DAY, T0 + 9 * DAY))
        self.assertGreater(len(lifecycle.weeks(T0 - 2 * DAY, T0 + 9 * DAY)), 1)


class StudyWindow(unittest.TestCase):
    """The bead's window (131 landed / 17,541 slot-min / 9,774 non-landing) as a synthetic fixture whose totals are fixed
    by construction (not by the code under test), laid over a window that crosses a UTC Monday."""

    def fixture(self):
        runs, t = [], T0 - 2 * DAY
        for i in range(131):  # 130 runs of 59 min and one of 97: 7,767 landed minutes
            mins = 97 if i == 0 else 59
            runs.append(trace("b%d" % i, "landed", (t - T0) / H, (t - T0) / H + mins / 60, sha="%040x" % i))
            t += 83 * M
        for i in range(60):  # 59 runs of 162 min and one of 216: 9,774 non-landing minutes
            mins = 216 if i == 0 else 162
            runs.append(trace("n%d" % i, "blocked", (t - T0) / H, (t - T0) / H + mins / 60, why="needs a human: x"))
            t += 170 * M
        return runs, T0 - 2 * DAY, t + DAY

    def test_the_study_totals_are_reproduced_within_two_percent(self):
        runs, since, until = self.fixture()
        w = lifecycle.lifecycle_report(runs, since=since, until=until, whole=True)["weeks"][0]
        self.assertEqual(w["landed_beads"], 131)
        self.assertAlmostEqual(w["slot_min"], 17541, delta=17541 * 0.02)
        self.assertAlmostEqual(w["non_landing_slot_min"], 9774, delta=9774 * 0.02)

    def test_weekly_buckets_add_up_to_the_whole_window(self):
        runs, since, until = self.fixture()
        whole = lifecycle.lifecycle_report(runs, since=since, until=until, whole=True)["weeks"]
        split = lifecycle.lifecycle_report(runs, since=since, until=until)["weeks"]
        self.assertGreater(len(split), 1)
        self.assertEqual(sum(x["landed_beads"] for x in split), whole[0]["landed_beads"])
        self.assertAlmostEqual(sum(x["slot_min"] for x in split), whole[0]["slot_min"], places=1)


class Cli(Base):
    def setUp(self):
        super().setUp()
        self.wt = str(self.repo / ".slots" / "s1")
        runs = [trace("a", "blocked", 1, 2, why="paused: lane out", worktree=self.wt),
                trace("a", "landed", 3, 3.5, sha="a" * 40, because="retry", worktree=self.wt,
                      sessions=[session("write", 100, 40)]),
                trace("b", "landed", 2, 4, sha="b" * 40, worktree=self.wt)]
        (tl.config_dir() / "engine").mkdir(parents=True, exist_ok=True)
        (tl.config_dir() / "asks").mkdir(parents=True, exist_ok=True)
        for r in runs:
            (tl.config_dir() / "engine" / (r["run"] + ".jsonl")).write_text("")
        (tl.config_dir() / "traces.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
        (tl.config_dir() / "asks" / "a-1.json").write_text(json.dumps(
            {"id": "a-1", "bead": "a", "kind": "verify", "why": "verify: x", "t": T0 + 2 * H}))
        self.history = [{"ts": T0 + 1 * H, "lane": "OPENAI", "model": "gpt", "status": "failed", "reason": "x"},
                        {"ts": T0 + 2 * H, "lane": "OPENAI", "model": "gpt", "status": "failed", "reason": "x"}]

    def args(self, *extra):
        return ["report", "lifecycle", "--repo", str(self.repo), "--since", "2026-10-19T00:00:00Z",
                "--until", "2026-10-26T00:00:00Z"] + list(extra)

    def test_the_real_cli_prints_named_text_lines_and_json(self):
        with mock.patch.object(report, "default_base", return_value="main"), \
                mock.patch.object(report, "history_rows", lambda: (self.history, True)), \
                mock.patch.object(report, "quota_snapshot", lambda **kw: {"available": False, "lanes": []}), \
                mock.patch.object(report, "lane_observations", lambda: []), \
                mock.patch.object(report, "reverts_of", lambda *a, **kw: {
                    "a-%d" % int(T0 + 3 * H): {"status": "clean"},
                    "b-%d" % int(T0 + 2 * H): {"status": "clean"}}):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = tl.main(self.args("--json"))
            self.assertEqual(rc, 0)
            d = json.loads(out.getvalue())
            self.assertEqual(d["weeks"][0]["landed_beads"], 2)
            self.assertEqual(d["weeks"][0]["avoidable_asks"], 1)
            self.assertEqual(d["weeks"][0]["fingerprint_streaks"][0]["max"], 2)
            out = io.StringIO()
            with redirect_stdout(out):
                tl.main(self.args())
            text = out.getvalue()
            for name in ("landed beads/day", "slot-min per landed bead", "non-landing slot-min share",
                         "avoidable asks/week", "beads landed on run 1", "runs per landed bead",
                         "median dead time", "fingerprint top-5", "max consecutive same-fingerprint",
                         "slot-min in runs >180 min", "verify-stage slot-min", "hung-step slot-min",
                         "median release-gate minutes", "uncached input tokens per landed bead",
                         "reverts per 100 landings", "quota % consumed per landed bead"):
                self.assertIn(name, text)

    def test_the_old_report_and_planner_still_parse(self):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = tl.main(["report", "--repo", str(self.repo), "--since", "2026-10-19T00:00:00Z",
                          "--until", "2026-10-26T00:00:00Z", "--planner"])
        self.assertEqual(rc, 0)


def git(repo, *args, t=None):
    env = dict(os.environ)
    if t is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "@%d +0000" % int(t)
    return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


def commit(repo, msg, t, allow_empty=False, body=None):
    args = ["commit", "-qm", msg]
    if allow_empty:
        args.insert(1, "--allow-empty")
    if body:
        args += ["-m", body]
    git(repo, *args, t=t)
    return git(repo, "rev-parse", "HEAD")


class Reverts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a").write_text("a\n")
        git(self.repo, "add", "-A")
        self.base = commit(self.repo, "init", T0 - H)

    def tearDown(self):
        def force(fn, path, _):
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        self.tmp.cleanup()

    def landing(self, sha, end_h):
        return {"bead": "t-1", "run": "t-1-1", "sha": sha, "started": T0 + (end_h - 0.5) * H,
                "ended": T0 + end_h * H, "outcome": "landed", "why": ""}

    def test_revert_is_linked_by_sha_but_an_unrelated_fix_is_not(self):
        (self.repo / "a").write_text("landed\n")
        git(self.repo, "add", "-A")
        sha = commit(self.repo, "land t-1", T0 + H)
        commit(self.repo, "Revert \"land t-1\"", T0 + 2 * H, allow_empty=True,
               body="This reverts commit %s." % sha)
        out = report.reverts_of(str(self.repo), [self.landing(sha, 1.5)], T0 + 9 * 24 * H, base="main")
        self.assertEqual(out["t-1-1"]["status"], "reverted")

        (self.repo / "b").write_text("b\n")
        git(self.repo, "add", "-A")
        sha2 = commit(self.repo, "land t-2", T0 + 3 * H)
        commit(self.repo, "fix a bug", T0 + 4 * H, allow_empty=True)
        out = report.reverts_of(str(self.repo), [self.landing(sha2, 3.5)], T0 + 9 * 24 * H, base="main")
        self.assertEqual(out["t-1-1"]["status"], "clean")

    def test_fixed_forward_must_name_the_landing(self):
        (self.repo / "a").write_text("landed\n")
        git(self.repo, "add", "-A")
        sha = commit(self.repo, "land t-1", T0 + H)
        commit(self.repo, "fix-forward %s" % sha[:12], T0 + 2 * H, allow_empty=True)
        out = report.reverts_of(str(self.repo), [self.landing(sha, 1.5)], T0 + 9 * 24 * H, base="main")
        self.assertEqual(out["t-1-1"]["status"], "fixed_forward")

    def test_seven_day_follow_up_is_censored(self):
        (self.repo / "a").write_text("landed\n")
        git(self.repo, "add", "-A")
        sha = commit(self.repo, "land t-1", T0 + H)
        out = report.reverts_of(str(self.repo), [self.landing(sha, 1.5)], T0 + 3 * 24 * H, base="main")
        self.assertEqual(out["t-1-1"]["status"], "censored")


if __name__ == "__main__":
    unittest.main()
