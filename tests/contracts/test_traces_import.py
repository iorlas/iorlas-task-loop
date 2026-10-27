"""dev/traces_import.py: v1 traces enter RunTrace v2 and `tl report lifecycle` reads the same numbers from them."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(ROOT / "dev"))
import lifecycle  # noqa: E402
import traces_import as ti  # noqa: E402
from taskloop.contracts import codec, stores, paths, trace  # noqa: E402

REAL = paths.ConfigDir().traces()
BASELINE = json.loads((ROOT / "docs" / "study" / "baselines-2026-10-25.json").read_text(encoding="utf-8"))
TZ = timezone(timedelta(hours=3))
SINCE = datetime(2026, 10, 18, 0, 0, tzinfo=TZ).timestamp()
UNTIL = datetime(2026, 10, 25, 20, 7, 28, tzinfo=TZ).timestamp()
LIFESIM = "https://github.com/yoselabs/lifesim.git"
# the baseline metrics a trace row alone decides (the rest read engine logs, ask files, delegate history or git)
TRACE_ONLY = ("landed_beads", "landed_beads_per_day", "slot_min", "slot_min_per_landed_bead", "non_landing_slot_min",
              "non_landing_slot_min_share", "beads_landed_on_run_1", "beads_touched", "landed_run1_share_touched", "runs",
              "runs_per_landed_bead", "dead_time_min", "fingerprint_top5", "slot_min_over_180", "uncached_input_tokens_per_landed_bead", "uncached_input")


def week(rows):
    return lifecycle.lifecycle_report(rows, since=SINCE, until=UNTIL, whole=True)["weeks"][0]


def row(run, **kw):
    t = datetime(2026, 10, 20, 10, 0).timestamp()
    base = {"v": 1, "run": run, "bead": run.rsplit("-", 2)[0], "repo": LIFESIM, "worktree": "/w", "branch": "b", "coordinator_session": "c",
            "started": t, "ended": t + 600.0, "outcome": "landed", "why": "", "sha": "abc", "sessions": []}
    base.update(kw)
    return base


MESSY = [
    row("lifesim-a-20261020-100000"),
    row("lifesim-a.1-20261020-110000", outcome="blocked", why="needs a human: x /tmp/a.py", started_because="retry", prev_run="p",
        stats={}, reflection=None, host=None, backfilled=True,
        sessions=[{"node": "plan", "family": "", "ref": "r", "transcript": "", "status": "done", "t": 1.0, "role": "planner",
                   "tokens": None, "denied": None, "context": {"env_keys": ["A"], "instructions": []}, "no_sandbox": True}]),
    row("lifesim-b-20261021-090000", started=1792600000, ended=1792600900, outcome="failed", why="busy: lane", fingerprint="busy#1",
        cost=0.5, stats={"writes": 1, "tokens_in": 9}, no_sandbox=True, ask="lifesim-b-1", lane_notes=["n"],
        reflection={"went_well": ["w"], "wasted": [], "change": ["c"],
                    "went_badly": [{"what": "x", "cause": "engine", "session": "s", "evidence": "e"}]},
        verified=[{"what": "w", "kind": "checkable", "verdict": "settled", "evidence": "e", "why": "y"}],
        write_rounds=[{"write": 1, "round": 1, "node_id": 2, "ref": "r", "resumed": "yes", "input_tokens": 5, "turns": None,
                       "context_k": None, "fresh": "session at 120k"}],
        sessions=[{"node": "write", "family": "zai", "ref": "r", "transcript": "/t", "status": "done", "t": 2.0, "role": "worker",
                   "tokens": {"in": 100, "cached": 40, "out": 7}, "secs": 5, "cost": 0.0, "turns": None, "flag": None,
                   "denied": [{"tool": "Bash", "input": {"command": "x"}}]}]),
]


class ImportRow(unittest.TestCase):
    def test_a_messy_row_becomes_a_valid_record_and_round_trips(self):
        for r in MESSY:
            with self.subTest(r["run"]):
                rec = ti.import_row(r)
                self.assertEqual(codec.from_json(trace.RunTrace, json.loads(json.dumps(codec.to_json(rec)))), rec)
                self.assertEqual(str(rec.run), r["run"])
                self.assertEqual(rec.repo_url, LIFESIM)

    def test_the_fields_the_report_reads_are_carried_exactly(self):
        w = week(MESSY)
        self.assertEqual(week([codec.to_json(ti.import_row(r)) for r in MESSY]), w)
        self.assertEqual((w["runs"], w["landed_beads"]), (3, 1))

    def test_the_fingerprint_is_carried_not_recomputed(self):
        self.assertEqual(ti.import_row(MESSY[2]).fingerprint, "busy#1")
        self.assertEqual(ti.import_row(MESSY[1]).fingerprint, "")

    def test_values_move_to_their_v2_homes(self):
        rec = ti.import_row(MESSY[2])
        self.assertEqual((rec.cost.usd, rec.stats.writes, rec.stats.tokens_in, rec.ask, rec.lane_notes), (0.5, 1, 9, "lifesim-b-1", ["n"]))
        self.assertEqual((rec.sessions[0].tokens, rec.sessions[0].denied[0].tool, rec.sessions[0].secs),
                         (trace.Tokens(in_=100, cached=40, out=7), "Bash", 5.0))
        self.assertEqual(rec.reflection.went_badly[0].cause, "engine")
        self.assertEqual(rec.write_rounds[0].fresh, "session at 120k")
        self.assertTrue(ti.import_row(MESSY[1]).backfilled)
        self.assertEqual(ti.import_row(MESSY[1]).sessions[0].tokens, trace.Tokens())

    def test_what_v2_does_not_carry_is_counted(self):
        self.assertEqual(ti.dropped_keys(MESSY[1]), ["session.context", "session.no_sandbox"])
        self.assertEqual(ti.dropped_keys(MESSY[2]), ["no_sandbox"])

    def test_a_row_that_is_not_v1_or_has_no_valid_run_is_refused(self):
        for bad in (dict(MESSY[0], v=2), dict(MESSY[0], run="nodate"), dict(MESSY[0], outcome="exploded"), {"v": 1}):
            with self.subTest(bad.get("run")):
                with self.assertRaises((ValueError, KeyError)):
                    ti.import_row(bad)


class ImportFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "traces.jsonl"
        self.src.write_text("".join(json.dumps(r) + "\n" for r in MESSY) + "torn\n[1]\n" + json.dumps(dict(MESSY[0], run="bad")) + "\n")

    def test_the_summary_counts_rows_refusals_and_dropped_keys(self):
        out = self.dir / "v2.jsonl"
        s = ti.import_file(self.src, out)
        self.assertEqual((s["read"], s["written"], len(s["refused"])), (4, 3, 3))
        self.assertEqual(s["dropped_keys"], {"no_sandbox": 1, "session.context": 1, "session.no_sandbox": 1})
        cfg = paths.ConfigDir(self.dir / "cfg")
        cfg.traces().parent.mkdir(parents=True)
        out.rename(cfg.traces())
        page = stores.TraceStore(cfg).read_from(0)
        self.assertEqual((len(page.items), page.skipped), (3, 0))

    def test_it_never_writes_its_source_nor_overwrites_without_force(self):
        before = self.src.read_text()
        with self.assertRaises(SystemExit):
            ti.import_file(self.src, self.src, force=True)
        out = self.dir / "o.jsonl"
        out.write_text("keep")
        with self.assertRaises(SystemExit):
            ti.import_file(self.src, out)
        self.assertEqual((out.read_text(), self.src.read_text()), ("keep", before))
        ti.import_file(self.src, out, force=True)
        self.assertEqual(len(out.read_text().splitlines()), 3)

    def test_main_prints_the_summary_and_fails_on_a_refused_row(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ti.main(["--src", str(self.src), "--out", str(self.dir / "m.jsonl")])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(buf.getvalue())["written"], 3)


@unittest.skipUnless(REAL.is_file(), "no ~/.config/task-loop/traces.jsonl on this machine")
class RealTraces(unittest.TestCase):
    """The 10-25 baseline window over the owner's real traces: the imported rows give the same report, to the last digit."""

    @classmethod
    def setUpClass(cls):
        rows, cls.bad = ti.read_v1(REAL)
        cls.rows = [r for r in rows if r.get("v") == 1]
        cls.lifesim = [r for r in cls.rows if r.get("repo") == LIFESIM or str(r.get("worktree")).startswith("/Users/iorlas/Workspaces/lifesim/")]

    def test_every_v1_row_imports(self):
        for r in self.rows:
            ti.import_row(r)

    def test_lifecycle_report_is_identical_before_and_after(self):
        imported = [codec.to_json(ti.import_row(r)) for r in self.lifesim]
        self.assertEqual(week(imported), week(self.lifesim))
        self.assertEqual(lifecycle.lifecycle_report(imported, since=SINCE, until=UNTIL), lifecycle.lifecycle_report(
            self.lifesim, since=SINCE, until=UNTIL))

    def test_the_trace_only_baseline_numbers_are_reproduced_with_zero_difference(self):
        w = week([codec.to_json(ti.import_row(r)) for r in self.lifesim])
        want = BASELINE["metrics"]
        self.assertGreater(w["runs"], 300)
        for k in TRACE_ONLY:
            with self.subTest(k):
                self.assertEqual(w[k], want[k])


if __name__ == "__main__":
    unittest.main()
