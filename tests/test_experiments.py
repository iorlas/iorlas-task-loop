"""tl-7y6.1.2 stage 1: the KPI registry, typed experiment sidecars, verdicts and the WIP cap.

The pure tests validate sidecars and due states by hand. The CLI tests run the real tl.main against a temporary repo
with the external adapters (lifecycle stats, repo traces) mocked, so no tracker, no git and no user config is read.
"""

import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import experiments  # noqa: E402
import lifecycle  # noqa: E402
import report  # noqa: E402
import tl  # noqa: E402

T0 = datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()  # Monday 00:00 UTC
H = 3600.0
DAY = 24 * H
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc).timestamp()  # the Monday a week later, noon UTC


def sidecar(metric="landed_beads_per_day", baseline=0.1, check_when=None, **kw):
    d = {"hypothesis": "smaller slices raise the beads landed per day",
         "metric": metric, "baseline": baseline,
         "check_when": check_when if check_when is not None else {"date": "2026-11-02"},
         "keep_if": "landed beads/day >= 0.14 for a whole week",
         "revert": "git revert the slice commits and re-freeze the baseline",
         "labels": ["experiment"], "created": "2026-10-26"}
    d.update(kw)
    return d


def trace(bead, outcome, start_h, end_h, why="", sha="", sessions=(), run=None):
    started, ended = T0 + start_h * H, T0 + end_h * H
    return {"v": 1, "run": run or "%s-%d" % (bead, int(started)), "bead": bead,
            "repo": "https://example.invalid/r.git", "worktree": "", "started": started, "ended": ended,
            "outcome": outcome, "why": why, "sha": sha, "started_because": "first",
            "fingerprint": lifecycle.run_fingerprint(outcome, why), "sessions": list(sessions), "stats": {}}


def rich_report(**kw):
    """One full week: two landed beads (one on its first run), a failure, verify and gate records, an ask, history."""
    traces = [
        trace("a", "failed", 1, 2, why="compile error in Assets/Player.cs"),
        trace("a", "landed", 3, 3.5, sha="a" * 40, sessions=[{"node": "write", "tokens": {"in": 100, "cached": 40}}]),
        trace("b", "landed", 2, 4, sha="b" * 40, sessions=[{"node": "write", "tokens": {"in": 50, "cached": 10}}]),
        trace("c", "failed", 5, 9, why="timeout: no answer", sessions=[{"node": "write", "tokens": {"in": 200}}]),
    ]
    records = {"a-%d" % int(T0 + 3 * H): [
        {"t": T0 + 3.1 * H, "kind": "node", "id": 1, "step": "verify", "text": "verify"},
        {"t": T0 + 3.2 * H, "kind": "end", "id": 1, "step": "verify", "text": "verify 1: done"},
        {"t": T0 + 3.4 * H, "kind": "gate", "text": "gate: exit 0", "secs": 120, "cached": False}]}
    asks = [{"id": "a-1", "bead": "a", "kind": "verify", "why": "verify: x", "t": T0 + 2 * H}]
    history = [{"ts": T0 + 1 * H, "lane": "L", "model": "m", "status": "failed", "reason": "boom"}]
    reverts = {"a-%d" % int(T0 + 3 * H): {"status": "reverted"}, "b-%d" % int(T0 + 2 * H): {"status": "clean"}}
    quota_obs = [{"t": T0 + 1 * H, "lane": "L", "window": "5h", "used_pct": 10},
                 {"t": T0 + 2 * H, "lane": "L", "window": "5h", "used_pct": 30}]
    base = dict(traces=traces, records_by_run=records, asks=asks, history=history, reverts=reverts,
                quota_observations=quota_obs, since=T0, until=T0 + 7 * DAY)
    base.update(kw)
    return lifecycle.lifecycle_report(**base)


class Repo(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / ".task" / "tmp"  # worktree-local temporary data, never the system temp dir
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(scratch), prefix="tl-test-experiments-")
        self.repo = Path(self.tmp.name) / "repo"
        (self.repo / ".task-loop" / "experiments").mkdir(parents=True)
        # The mocked external git adapter: asked for the repo's common dir it names this repo (as real git answers
        # from any subdirectory of a repository); everything else fails, as git does outside any repository. No git
        # command is run by these tests.
        p = mock.patch.object(tl, "git", self.git)
        p.start()
        self.addCleanup(p.stop)

    def git(self, *args, **kw):
        if "--git-common-dir" in args:
            return str(self.repo / ".git")
        return ""

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, bead, data, raw=None):
        p = self.repo / ".task-loop" / "experiments" / ("%s.json" % bead)
        p.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
        return p

    def stats(self, **row):
        week = {"unavailable": [], "landed_beads_per_day": 0.29, "slot_min_per_landed": 225.0}
        week.update(row)
        return {"v": 1, "weeks": [week]}


# ---- the sidecar contract ---------------------------------------------------------------------------------------------

class SidecarContract(Repo):
    def test_a_valid_sidecar_parses_with_both_check_when_forms(self):
        for cw in ({"date": "2026-11-02"}, {"runs": 5, "since": "2026-10-26"}):
            exp = experiments.parse_sidecar("tl-a1", sidecar(check_when=cw))
            self.assertEqual(exp["metric"], "landed_beads_per_day")
            self.assertEqual(exp["metric_label"], "landed beads/day")
            self.assertEqual(exp["check_when"], cw)
            self.assertIsNone(exp["verdict"])

    def test_an_unknown_metric_is_rejected_with_the_list_of_valid_ids(self):
        with self.assertRaises(experiments.ExperimentError) as cm:
            experiments.parse_sidecar("tl-a1", sidecar(metric="landed_beads"))
        msg = str(cm.exception)
        self.assertIn("unknown metric", msg)
        for k in lifecycle.KPIS:  # every valid id is named, so the fix is a one-read
            self.assertIn(k["id"], msg)

    def test_the_baseline_must_be_a_number(self):
        for bad in ("0.1", None, True, [0.1]):
            with self.assertRaises(experiments.ExperimentError):
                experiments.parse_sidecar("tl-a1", sidecar(baseline=bad))

    def test_check_when_is_a_date_or_positive_runs_with_an_explicit_anchor(self):
        for bad in ({}, {"runs": 5}, {"runs": 0, "since": "2026-10-26"}, {"runs": -2, "since": "2026-10-26"},
                    {"runs": 1.5, "since": "2026-10-26"}, {"runs": 5, "since": "2026-10-26", "x": 1},
                    {"date": "2026-11-02", "runs": 5, "since": "2026-10-26"}, {"date": "2026-11-02", "since": "x"},
                    {"date": "2026-02-30"}, {"date": "not-a-date"}, {"runs": "5", "since": "2026-10-26"},
                    {"date": None}, {"runs": True, "since": "2026-10-26"}):
            with self.assertRaises(experiments.ExperimentError):
                experiments.parse_sidecar("tl-a1", sidecar(check_when=bad))

    def test_the_text_fields_must_be_non_empty_strings(self):
        for field in ("hypothesis", "keep_if", "revert"):
            for bad in ("", "   ", None, 5):
                d = sidecar()
                d[field] = bad
                with self.assertRaises(experiments.ExperimentError):
                    experiments.parse_sidecar("tl-a1", d)

    def test_a_bead_labelled_bet_is_rejected_as_an_experiment(self):
        for labels in (["bet"], ["experiment", "bet"], ["Experiment", "BET"]):
            with self.assertRaises(experiments.ExperimentError) as cm:
                experiments.parse_sidecar("tl-a1", sidecar(labels=labels))
            self.assertIn("bet", str(cm.exception))

    def test_unknown_fields_are_rejected_with_the_valid_ones(self):
        with self.assertRaises(experiments.ExperimentError) as cm:
            experiments.parse_sidecar("tl-a1", sidecar(keep="beads/day >= 0.14"))
        msg = str(cm.exception)
        self.assertIn("keep", msg)
        for f in experiments.FIELDS:
            self.assertIn(f, msg)

    def test_a_verdict_must_be_a_known_kind_with_a_real_date(self):
        for bad in ({"kind": "keep"}, {"kind": "hold", "date": "2026-11-03"}, {"kind": "keep", "date": "x"},
                    {"kind": "keep", "date": "2026-11-03", "note": "ok"}, "keep", []):
            with self.assertRaises(experiments.ExperimentError):
                experiments.parse_sidecar("tl-a1", sidecar(verdict=bad))
        exp = experiments.parse_sidecar("tl-a1", sidecar(verdict={"kind": "extend", "date": "2026-11-03"}))
        self.assertEqual(exp["verdict"], {"kind": "extend", "date": "2026-11-03"})

    def test_a_bad_bead_id_or_bad_shape_is_rejected(self):
        for bead in ("", "a b", "../esc", ".hidden", "-lead", "sp ace"):
            with self.assertRaises(experiments.ExperimentError):
                experiments.parse_sidecar(bead, sidecar())
        with self.assertRaises(experiments.ExperimentError):
            experiments.parse_sidecar("tl-a1", [1, 2])

    def test_loading_rejects_invalid_json_and_bad_ids_but_keeps_the_rest(self):
        self.write("tl-a1", sidecar())
        self.write("tl-b2", None, raw="{not json")
        self.write("bad id", sidecar())
        self.write("tl-c3", sidecar(labels=["bet"]))
        d = experiments.load_experiments(str(self.repo))
        self.assertEqual([x["bead"] for x in d["open"]], ["tl-a1"])
        self.assertEqual({x["bead"] for x in d["rejected"]}, {"tl-b2", "bad id", "tl-c3"})
        for x in d["rejected"]:
            self.assertTrue(x["why"])


# ---- the KPI registry -------------------------------------------------------------------------------------------------

class MetricRegistry(unittest.TestCase):
    def test_every_kpi_is_an_existing_week_key_and_the_value_passes_through(self):
        w = rich_report()["weeks"][0]
        self.assertEqual(len(lifecycle.KPI_BY_ID), len(lifecycle.KPIS))
        for k in lifecycle.KPIS:
            self.assertIn(k["key"], w, k["id"])
            self.assertEqual(lifecycle.kpi_value(w, k["id"]), w[k["key"]], k["id"])

    def test_the_numbers_the_registry_passes_are_the_numbers_the_report_computed(self):
        w = rich_report()["weeks"][0]
        self.assertEqual(lifecycle.kpi_value(w, "landed_beads_per_day"), round(2 / 7, 2))
        self.assertEqual(lifecycle.kpi_value(w, "slot_min_per_landed"), 225.0)
        self.assertEqual(lifecycle.kpi_value(w, "non_landing_slot_min_share"), round(300 / 450, 4))
        self.assertEqual(lifecycle.kpi_value(w, "runs_per_landed"), 2.0)
        self.assertEqual(lifecycle.kpi_value(w, "landed_run1_share"), 0.5)
        self.assertEqual(lifecycle.kpi_value(w, "median_release_gate_minutes"), 2.0)
        self.assertEqual(lifecycle.kpi_value(w, "uncached_input_tokens_per_landed_bead"), 150.0)
        self.assertEqual(lifecycle.kpi_value(w, "reverts_per_100_landings"), 50.0)
        self.assertEqual(lifecycle.kpi_value(w, "quota_percent_per_landed_bead"), 10.0)

    def test_unavailable_tokens_match_what_the_report_marks_unavailable(self):
        # one blocked run, no landings: every per-landed denominator is unavailable, never 0
        w = lifecycle.lifecycle_report([trace("a", "blocked", 1, 2, why="boom")], records_by_run={}, asks=[],
                                      history=[], since=T0, until=T0 + 7 * DAY)["weeks"][0]
        for k in lifecycle.KPIS:
            token = k.get("unavailable")
            if not token or token == "non-landing-slot-min-share":  # the share is computable here (its own test below)
                continue
            self.assertIn(token, w["unavailable"], k["id"])
            self.assertIsNone(lifecycle.kpi_value(w, k["id"]), k["id"])
        self.assertEqual(lifecycle.kpi_value(w, "landed_beads_per_day"), 0.0)  # still a real measure, not unavailable

    def test_a_missing_span_makes_the_share_unavailable(self):
        w = lifecycle.lifecycle_report([{"bead": "x", "run": "x-1", "started": T0 + H, "outcome": "failed",
                                         "why": "boom"}], records_by_run={}, asks=[], history=[],
                                      since=T0, until=T0 + 7 * DAY)["weeks"][0]
        self.assertIn("non-landing-slot-min-share", w["unavailable"])
        self.assertIsNone(lifecycle.kpi_value(w, "non_landing_slot_min_share"))

    def test_every_id_is_printed_by_the_lifecycle_report(self):
        w = rich_report()["weeks"][0]
        out = io.StringIO()
        with redirect_stdout(out):
            report.print_lifecycle({"since_iso": "", "until_iso": "", "weeks": [w]})
        text = out.getvalue()
        for k in lifecycle.KPIS:
            self.assertIn("[%s]" % k["id"], text, k["id"])
            self.assertIn(k["label"], text, k["id"])

    def test_a_metric_outside_the_registry_is_not_a_kpi_id(self):
        self.assertIsNone(lifecycle.KPI_BY_ID.get("landed_beads"))
        self.assertIsNone(lifecycle.kpi_value({}, "landed_beads"))
        self.assertIsNone(lifecycle.kpi_value(None, "landed_beads_per_day"))


class RegistryRegression(unittest.TestCase):
    FIXTURE = ROOT / "tests" / "fixtures" / "lifecycle"

    def report(self):
        return lifecycle.lifecycle_report(report.read_jsonl(self.FIXTURE / "traces.jsonl"), records_by_run=None,
                                          asks=report.read_jsonl(self.FIXTURE / "asks.jsonl"),
                                          history=report.read_jsonl(self.FIXTURE / "history.jsonl"),
                                          since=T0, until=T0 + 7 * DAY)

    def lines(self, r):
        out = io.StringIO()
        with redirect_stdout(out):
            report.print_lifecycle(r)
        return out.getvalue()

    def test_the_checked_in_fixture_numbers_are_unchanged_through_the_registry(self):
        w = self.report()["weeks"][0]
        self.assertEqual(lifecycle.kpi_value(w, "landed_beads_per_day"), round(1 / 7, 2))
        self.assertEqual(lifecycle.kpi_value(w, "slot_min_per_landed"), 120.0)
        self.assertEqual(lifecycle.kpi_value(w, "non_landing_slot_min_share"), 0.5)
        self.assertEqual(lifecycle.kpi_value(w, "landed_run1_share"), 1.0)
        self.assertEqual(lifecycle.kpi_value(w, "runs_per_landed"), 2.0)
        self.assertEqual(lifecycle.kpi_value(w, "avoidable_asks_per_week"), 1)
        self.assertEqual(lifecycle.kpi_value(w, "uncached_input_tokens_per_landed_bead"), 60.0)

    def test_print_lifecycle_keeps_the_contract_lines_and_adds_the_ids(self):
        text = self.lines(self.report())
        for name in ("landed beads/day", "slot-min per landed bead", "non-landing slot-min share",
                     "avoidable asks/week", "beads landed on run 1", "runs per landed bead",
                     "median dead time per started_because", "fingerprint top-5 (beads/day)",
                     "max consecutive same-fingerprint non-done runs per (lane,model)",
                     "slot-min in runs >180 min", "verify-stage slot-min", "hung-step slot-min",
                     "median release-gate minutes", "uncached input tokens per landed bead",
                     "reverts per 100 landings", "quota % consumed per landed bead"):
            self.assertRegex(text, r"(?m)^  " + re.escape(name) + r"( \(min\))?:", name)
        for k in lifecycle.KPIS:
            self.assertIn("[%s]" % k["id"], text, k["id"])

    def test_the_registry_only_names_keys_never_recalculates(self):
        w = self.report()["weeks"][0]
        for k in lifecycle.KPIS:  # the id names the row's own key: no second calculation exists to drift
            self.assertEqual(lifecycle.kpi_value(w, k["id"]), w[k["key"]], k["id"])
        self.assertTrue(all(k["key"] in lifecycle.lifecycle_report([], since=T0, until=T0 + DAY)["weeks"][0]
                            for k in lifecycle.KPIS))


# ---- due states and verdicts -----------------------------------------------------------------------------------------

class DueAndVerdict(Repo):
    def traces(self):
        return [trace("tl-a1", "failed", 24, 25), trace("tl-a1", "failed", 48, 49),
                trace("tl-b2", "failed", 24, 25), {"bead": "tl-a1", "started": "nope"},
                {"bead": "tl-a1", "run": "tl-a1-x"}]

    def test_a_date_is_due_on_its_day_and_overdue_the_day_after(self):
        exp = experiments.parse_sidecar("tl-a1", sidecar(check_when={"date": "2026-10-28"}))
        self.assertEqual(experiments.due(exp, datetime(2026, 10, 26, tzinfo=timezone.utc).timestamp())["state"],
                         "waiting")
        self.assertEqual(experiments.due(exp, datetime(2026, 10, 28, 23, tzinfo=timezone.utc).timestamp()),
                         {"state": "due", "kind": "date", "date": "2026-10-28"})
        d = experiments.due(exp, datetime(2026, 10, 31, tzinfo=timezone.utc).timestamp())
        self.assertEqual((d["state"], d["overdue_days"]), ("overdue", 3))

    def test_runs_are_due_at_n_and_overdue_past_n(self):
        exp = experiments.parse_sidecar("tl-a1", sidecar(check_when={"runs": 2, "since": "2026-10-20"}))
        self.assertEqual(experiments.due(exp, NOW, 1)["state"], "waiting")
        self.assertEqual(experiments.due(exp, NOW, 2)["state"], "due")
        d = experiments.due(exp, NOW, 5)
        self.assertEqual((d["state"], d["overdue_runs"]), ("overdue", 3))

    def test_runs_since_the_anchor_count_only_that_bead_from_that_day(self):
        t = self.traces()  # tl-a1 has two runs started Mon/Tue 2026-10-20 (T0+1d, T0+2d); the anchor day is the 20th
        self.assertEqual(experiments.runs_since(t, "tl-a1", experiments.day_start("2026-10-20")), 2)
        self.assertEqual(experiments.runs_since(t, "tl-a1", experiments.day_start("2026-10-21")), 1)
        self.assertEqual(experiments.runs_since(t, "tl-b2", experiments.day_start("2026-10-20")), 1)

    def test_an_overdue_open_experiment_is_flagged_no_verdict_in_text_and_json(self):
        self.write("tl-a1", sidecar(check_when={"date": "2026-10-20"}))
        self.write("tl-b2", sidecar(metric="avoidable_asks_per_week", baseline=1,
                                    check_when={"date": "2026-11-20"}))
        r = experiments.experiments_report(str(self.repo), T0, T0 + 7 * DAY, now=NOW, traces=[],
                                           stats=self.stats())
        self.assertEqual(r["overdue_no_verdict"], ["tl-a1"])
        out = io.StringIO()
        with redirect_stdout(out):
            experiments.print_experiments(r)
        text = out.getvalue()
        self.assertIn("NO VERDICT", text)
        self.assertIn("overdue with NO VERDICT: tl-a1", text)
        b2 = [ln for ln in text.splitlines() if "tl-b2" in ln or "2026-11-20" in ln]
        self.assertTrue(b2)
        self.assertFalse(any("NO VERDICT" in ln for ln in b2))  # the not-yet-due one stays silent

    def test_the_current_metric_comes_from_the_window_and_stays_unavailable_when_it_cannot_be_computed(self):
        self.write("tl-a1", sidecar(baseline=0.1))
        self.write("tl-b2", sidecar(metric="median_release_gate_minutes", baseline=3.0))
        r = experiments.experiments_report(str(self.repo), T0, T0 + 7 * DAY, now=NOW, traces=[],
                                           stats=self.stats(median_release_gate_minutes=None,
                                                            unavailable=["median-release-gate-minutes"]))
        currents = {x["bead"]: x["current"] for x in r["open"]}
        self.assertEqual(currents["tl-a1"], 0.29)
        self.assertIsNone(currents["tl-b2"])
        self.assertTrue(next(x for x in r["open"] if x["bead"] == "tl-b2")["current_unavailable"])

    def test_verdict_closes_the_experiment_records_the_date_and_persists(self):
        self.write("tl-v1", sidecar(check_when={"runs": 2, "since": "2026-10-20"}))
        with mock.patch.object(experiments, "lifecycle_stats", lambda *a: self.stats()), \
                mock.patch.object(experiments, "repo_traces", lambda *a: self.traces()):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = tl.main(["experiments", "verdict", "tl-v1", "keep", "--repo", str(self.repo),
                              "--date", "2026-10-26"])
        self.assertEqual(rc, 0)
        self.assertIn("VERDICT tl-v1 keep 2026-10-26", out.getvalue())
        kept = json.loads((self.repo / ".task-loop" / "experiments" / "tl-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(kept["verdict"], {"kind": "keep", "date": "2026-10-26"})
        d = experiments.load_experiments(str(self.repo))  # the reload sees the closure too
        self.assertEqual([x["bead"] for x in d["closed"]], ["tl-v1"])
        self.assertEqual(d["open"], [])
        r = experiments.experiments_report(str(self.repo), T0, T0 + 7 * DAY, now=NOW, traces=self.traces(),
                                           stats=self.stats())
        self.assertEqual(r["open_count"], 0)

    def test_each_verdict_kind_closes_its_experiment(self):
        for i, kind in enumerate(experiments.VERDICT_KINDS):
            bead = "tl-k%d" % i
            self.write(bead, sidecar(check_when={"date": "2026-11-0%d" % (i + 1)}))
            with redirect_stdout(io.StringIO()):
                rc = tl.main(["experiments", "verdict", bead, kind, "--repo", str(self.repo),
                              "--date", "2026-10-26"])
            self.assertEqual(rc, 0)
        d = experiments.load_experiments(str(self.repo))
        self.assertEqual({x["verdict"]["kind"] for x in d["closed"]}, set(experiments.VERDICT_KINDS))

    def test_verdict_from_a_subdirectory_finds_the_record(self):
        self.write("tl-v1", sidecar())
        sub = self.repo / "nested" / "dir"
        sub.mkdir(parents=True)
        was = os.getcwd()
        os.chdir(sub)
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = tl.main(["experiments", "verdict", "tl-v1", "keep", "--date", "2026-10-26"])  # no --repo
        finally:
            os.chdir(was)
        self.assertEqual(rc, 0)
        self.assertIn("VERDICT tl-v1 keep 2026-10-26", out.getvalue())
        kept = json.loads((self.repo / ".task-loop" / "experiments" / "tl-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(kept["verdict"], {"kind": "keep", "date": "2026-10-26"})

    def test_an_invalid_verdict_is_rejected_and_a_closed_one_is_not_reverdicted(self):
        self.write("tl-v1", sidecar())
        for args in (["experiments", "verdict", "tl-v1", "hold", "--repo", str(self.repo)],
                     ["experiments", "verdict", "tl-nope", "keep", "--repo", str(self.repo)],
                     ["experiments", "verdict", "tl-v1", "keep", "--repo", str(self.repo), "--date", "2026-13-01"]):
            with mock.patch.object(sys, "stderr", io.StringIO()):
                with redirect_stdout(io.StringIO()):
                    rc = tl.main(args)
            self.assertNotEqual(rc, 0, args)
        with redirect_stdout(io.StringIO()):
            rc = tl.main(["experiments", "verdict", "tl-v1", "keep", "--repo", str(self.repo),
                          "--date", "2026-10-26"])
        self.assertEqual(rc, 0)
        with mock.patch.object(sys, "stderr", io.StringIO()) as err:
            with redirect_stdout(io.StringIO()):
                rc = tl.main(["experiments", "verdict", "tl-v1", "revert", "--repo", str(self.repo),
                              "--date", "2026-10-27"])
        self.assertNotEqual(rc, 0)
        self.assertIn("not re-verdicted", err.getvalue())
        kept = json.loads((self.repo / ".task-loop" / "experiments" / "tl-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(kept["verdict"]["kind"], "keep")  # the first verdict stands


# ---- the WIP cap ------------------------------------------------------------------------------------------------------

class WorkInProgress(Repo):
    def cli(self, *args, **kw):
        argv = ["experiments"] + list(args)
        if kw.get("repo", True):
            argv += ["--repo", str(self.repo)]
        with mock.patch.object(experiments, "lifecycle_stats", lambda *a: self.stats()), \
                mock.patch.object(experiments, "repo_traces", lambda *a: []):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = tl.main(argv)
        return rc, out.getvalue()

    def in_dir(self, cwd, *args):
        """The CLI as run from inside `cwd` with no --repo: the repo must resolve from there (tl.repo_root)."""
        cwd.mkdir(parents=True, exist_ok=True)
        was = os.getcwd()
        os.chdir(cwd)
        try:
            return self.cli(*args, repo=False)
        finally:
            os.chdir(was)

    def eight(self):
        for i in range(8):  # eight open fixtures: dates and run counts both present
            cw = {"date": "2026-11-%02d" % (i + 1)} if i % 2 else {"runs": i + 1, "since": "2026-10-26"}
            self.write("tl-w%d" % i, sidecar(metric="landed_beads_per_day", baseline=0.1, check_when=cw))

    def test_check_exits_0_at_eight_open(self):
        self.eight()
        rc, text = self.cli("check")
        self.assertEqual(rc, 0)
        self.assertIn("8 open (cap 8)", text)

    def test_check_exits_1_at_nine_open(self):
        self.eight()
        self.write("tl-w8", sidecar(metric="runs_per_landed", baseline=2.0, check_when={"runs": 3,
                                                                                        "since": "2026-10-26"}))
        rc, text = self.cli("check")
        self.assertEqual(rc, 1)
        self.assertIn("WIP cap exceeded", text)
        self.assertIn("9 open", text)
        rc, d = self.cli("check", "--json")
        self.assertEqual(rc, 1)
        j = json.loads(d)
        self.assertEqual(j["open_count"], 9)
        self.assertTrue(j["over_cap"])

    def test_verdict_closed_records_do_not_count_toward_the_cap(self):
        self.eight()
        self.write("tl-w8", sidecar(verdict={"kind": "revert", "date": "2026-10-25"}))
        rc, text = self.cli("check")
        self.assertEqual(rc, 0)
        self.assertIn("closed: verdict revert 2026-10-25", text)

    def test_a_bead_labelled_bet_is_rejected_by_check_and_never_counts_as_open(self):
        self.eight()
        self.write("tl-bet", sidecar(labels=["experiment", "bet"]))
        rc, d = self.cli("check", "--json")
        self.assertEqual(rc, 1)
        j = json.loads(d)
        self.assertEqual(j["open_count"], 8)  # the bet is not the ninth experiment
        self.assertEqual([x["bead"] for x in j["rejected"]], ["tl-bet"])
        rc, text = self.cli("check")
        self.assertIn("REJECTED", text)
        self.assertIn("bet", text)

    def test_the_list_report_shows_current_metric_against_baseline(self):
        self.eight()
        rc, text = self.cli()
        self.assertEqual(rc, 0)
        self.assertIn("baseline 0.1", text)
        self.assertIn("current 0.29", text)
        self.assertIn("check_when runs 0/1 since 2026-10-26", text)
        self.assertIn("check_when date 2026-11-02", text)

    def test_from_a_subdirectory_list_finds_the_repo_and_its_sidecars(self):
        self.eight()
        rc, text = self.in_dir(self.repo / "deep" / "sub", "list")
        self.assertEqual(rc, 0)
        self.assertIn("8 open (cap 8)", text)
        self.assertIn("current 0.29", text)

    def test_from_a_subdirectory_check_still_exits_1_over_the_cap(self):
        self.eight()
        self.write("tl-w8", sidecar(metric="runs_per_landed", baseline=2.0, check_when={"runs": 3,
                                                                                        "since": "2026-10-26"}))
        rc, text = self.in_dir(self.repo / "deep" / "sub", "check")
        self.assertEqual(rc, 1)
        self.assertIn("WIP cap exceeded", text)
        self.assertIn("9 open", text)


if __name__ == "__main__":
    unittest.main()
