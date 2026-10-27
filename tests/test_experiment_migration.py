"""tl-7y6.1.2 stage 2: the one-off importer from a bead snapshot into typed experiment sidecars.

The importer runs as a real subprocess (python3 dev/migrate_experiments.py) against synthetic snapshots in a
temporary repo under this worktree: no tracker, no git, no user config is read or written. The checked-in fixture is
deliberately synthetic (tests/fixtures/experiments/migration-beads.json); the real stage snapshot does not exist in
the worktree yet (docs/study/README.md).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "dev" / "migrate_experiments.py"
FIXTURE = ROOT / "tests" / "fixtures" / "experiments" / "migration-beads.json"
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import experiments  # noqa: E402  (the stage-1 contract this importer must satisfy)


def block(**over):
    """A synthetic Experiment block: pass None to drop a field, a string to change it."""
    f = {"hypothesis": "a synthetic hypothesis for the importer tests",
         "metric": "landed beads/day",
         "baseline": "0.14",
         "check_when": "date 2026-11-02",
         "keep_if": "the synthetic keep condition holds",
         "revert": "the synthetic pre-written revert"}
    f.update(over)
    return "\n".join("%s: %s" % (k, v) for k, v in f.items() if v is not None)


def bead(bid, body=None, labels=(), **kw):
    b = {"id": bid, "title": "Synthetic %s" % bid, "status": "open", "labels": list(labels),
         "created_at": "2026-10-26T09:30:00Z"}
    b.update(kw)
    b["description"] = ("## Experiment\n" + (body if body is not None else block())) + "\n"
    return b


def sidecar(**kw):
    """A valid pre-existing stage-1 sidecar for beads the snapshot does not mention."""
    d = {"hypothesis": "a pre-existing experiment", "metric": "landed_beads_per_day", "baseline": 0.1,
         "check_when": {"date": "2026-11-02"}, "keep_if": "the keep condition holds",
         "revert": "the pre-written revert", "labels": ["experiment"], "verdict": None}
    d.update(kw)
    return d


class Import(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / ".task" / "tmp"  # worktree-local temporary data, never the system temp dir
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(scratch), prefix="tl-test-migration-")
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def run_import(self, snapshot, mappings=None, repo=None, json_mode=False):
        cmd = [sys.executable, str(SCRIPT), "--snapshot", str(snapshot), "--repo", str(repo or self.repo)]
        if mappings is not None:
            cmd += ["--mappings", str(mappings)]
        if json_mode:
            cmd += ["--json"]
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              cwd=str(ROOT), timeout=60)

    def snapshot(self, beads, name="snapshot.json"):
        p = Path(self.tmp.name) / name
        p.write_text(json.dumps({"v": 1, "beads": beads}), encoding="utf-8")
        return p

    def mappings(self, data, name="mappings.json"):
        p = Path(self.tmp.name) / name
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def sidecars(self, repo=None):
        return sorted(experiments.sidecar_dir(repo or self.repo).glob("*.json"))

    def seed(self, bid, data):
        d = experiments.sidecar_dir(self.repo)
        d.mkdir(parents=True, exist_ok=True)
        p = d / ("%s.json" % bid)
        p.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return p

    def fixture_beads(self, extra=()):
        beads = json.loads(FIXTURE.read_text(encoding="utf-8"))["beads"]
        return beads + list(extra)


class FixtureImport(Import):
    def test_the_eight_synthetic_experiments_become_eight_valid_sidecars(self):
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.sidecars()), 8)
        loaded = experiments.load_experiments(str(self.repo))
        self.assertEqual([x["bead"] for x in loaded["open"]],
                         ["syn-0%d" % i for i in range(1, 9)])
        self.assertEqual(loaded["closed"], [])
        self.assertEqual(loaded["rejected"], [])
        self.assertIn("imported 8, unchanged 0, kept 0, ignored 3; open now 8 (cap 8)", r.stdout)

    def test_metric_names_are_normalized_through_the_shared_registry(self):
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 0, r.stderr)
        want = {"syn-01": "landed_beads_per_day",    # the label "landed beads/day"
                "syn-02": "slot_min_per_landed",     # the id itself
                "syn-03": "avoidable_asks_per_week",
                "syn-04": "median_release_gate_minutes",
                "syn-05": "landed_run1_share",
                "syn-06": "reverts_per_100_landings",
                "syn-07": "runs_per_landed",
                "syn-08": "non_landing_slot_min_share"}
        loaded = {x["bead"]: x for x in experiments.load_experiments(str(self.repo))["open"]}
        for bid, metric in want.items():
            self.assertEqual(loaded[bid]["metric"], metric, bid)

    def test_source_text_labels_and_created_dates_survive(self):
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 0, r.stderr)
        loaded = {x["bead"]: x for x in experiments.load_experiments(str(self.repo))["open"]}
        self.assertEqual(loaded["syn-01"]["created"], "2026-10-26")   # from the bead's created_at
        self.assertEqual(loaded["syn-02"]["created"], "2026-10-27")   # the block's own created line wins
        self.assertEqual(loaded["syn-03"]["created"], "2026-10-25")
        self.assertEqual(loaded["syn-08"]["labels"], ["auto", "experiment"])  # bead labels pass through, deduped
        self.assertEqual(loaded["syn-06"]["hypothesis"],
                         "linking each revert to its landing within a week lowers reverts per 100 landings")
        self.assertEqual(loaded["syn-07"]["check_when"], {"date": "2026-11-23"})
        self.assertEqual(loaded["syn-08"]["check_when"], {"runs": 1, "since": "2026-10-26"})

    def test_only_the_experiment_block_is_extracted(self):
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 0, r.stderr)
        loaded = {x["bead"]: x for x in experiments.load_experiments(str(self.repo))["open"]}
        self.assertEqual(loaded["syn-05"]["metric"], "landed_run1_share")  # not the decoys around it
        self.assertNotIn("DECOY", json.dumps(loaded))
        self.assertNotIn("2099-01-01", json.dumps(loaded))
        self.assertEqual([p.stem for p in self.sidecars()],
                         ["syn-0%d" % i for i in range(1, 9)])  # syn-plain, syn-plural, syn-empty: no sidecar

    def test_counting_is_by_verdict_not_bead_status(self):
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 0, r.stderr)
        loaded = {x["bead"]: x for x in experiments.load_experiments(str(self.repo))["open"]}
        self.assertIn("syn-07", loaded)  # the closed bead's experiment is still open: only a verdict closes one
        self.assertIsNone(loaded["syn-07"]["verdict"])
        self.assertEqual(experiments.load_experiments(str(self.repo))["closed"], [])

    def test_the_json_report_carries_the_provenance(self):
        r = self.run_import(FIXTURE, json_mode=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(r.stdout)
        self.assertEqual(len(j["imported"]), 8)
        self.assertEqual(j["open_after"], 8)
        self.assertEqual(j["cap"], experiments.CAP)
        for x in j["imported"]:
            self.assertEqual(x["bead"], x["source"]["bead"])
            self.assertTrue(x["source"]["title"])
            self.assertTrue(x["source"]["block"].lstrip().startswith("hypothesis:"))
            self.assertTrue(x["source"]["snapshot"].endswith("migration-beads.json"))
        self.assertEqual([x["bead"] for x in j["ignored"]], ["syn-empty", "syn-plain", "syn-plural"])


class Rejections(Import):
    def test_nine_open_records_reject_the_whole_import(self):
        p = self.snapshot(self.fixture_beads([bead("syn-09")]))
        r = self.run_import(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("would leave 9 experiments open (cap 8)", r.stderr)
        self.assertEqual(self.sidecars(), [])  # nothing was written

    def test_a_bead_labelled_bet_is_rejected_and_nothing_is_written(self):
        p = self.snapshot(self.fixture_beads([bead("syn-bet", labels=["experiment", "bet"])]))
        r = self.run_import(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("bet", r.stderr)
        self.assertIn("syn-bet", r.stderr)
        self.assertEqual(self.sidecars(), [])

    def test_unknown_metric_names_are_rejected_with_the_valid_ones(self):
        p = self.snapshot([bead("syn-m1", body=block(metric="beads per day"))])
        r = self.run_import(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("'beads per day' is not a KPI", r.stderr)
        for needle in ("landed_beads_per_day", "slot_min_per_landed", "avoidable asks/week",
                       "reverts_per_100_landings"):
            self.assertIn(needle, r.stderr)
        self.assertEqual(self.sidecars(), [])

    def test_prose_baselines_and_triggers_are_never_reinterpreted(self):
        for check_when in ("after 5 asks settle", "next release", "3-5 runs since 2026-10-26", "soon"):
            p = self.snapshot([bead("syn-p1", body=block(check_when=check_when))])
            r = self.run_import(p)
            self.assertEqual(r.returncode, 1, check_when)
            self.assertIn("cannot be typed faithfully", r.stderr)
            self.assertIn("mappings", r.stderr)
            self.assertEqual(self.sidecars(), [])
        p = self.snapshot([bead("syn-p2", body=block(baseline="about a third"))])
        r = self.run_import(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("baseline 'about a third' is prose", r.stderr)
        self.assertEqual(self.sidecars(), [])

    def test_duplicate_path_escaping_and_incomplete_records_reject(self):
        p = self.snapshot([bead("dup-1"), bead("dup-1", body=block(baseline="0.2"))])
        r = self.run_import(p)
        self.assertEqual(r.returncode, 2)  # the snapshot's shape is broken, not its beads' content
        self.assertIn("dup-1 appears twice", r.stderr)
        p = self.snapshot([bead("../esc")])
        r = self.run_import(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("is not a bead id a sidecar may be named after", r.stderr)
        p = self.snapshot([bead("syn-x1", body=block(revert=None))])
        r = self.run_import(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("states no revert", r.stderr)
        p = self.snapshot([bead("syn-x2", body=block(check_when="date 2026-02-30"))])
        r = self.run_import(p)
        self.assertEqual(r.returncode, 1)
        self.assertIn("syn-x2", r.stderr)
        self.assertEqual(self.sidecars(), [])

    def test_a_failed_import_preserves_existing_sidecars_and_writes_nothing_partial(self):
        old = self.seed("old-1", sidecar())
        before = old.read_text(encoding="utf-8")
        p = self.snapshot([bead("syn-a1"), bead("syn-bad", body=block(metric="nope")),
                           bead("syn-a2", body=block(baseline="0.2"))])
        r = self.run_import(p)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(old.read_text(encoding="utf-8"), before)  # the pre-existing sidecar stands
        self.assertEqual([p.stem for p in self.sidecars()], ["old-1"])  # and no partial write happened

    def test_a_failed_import_never_touches_the_snapshot_beads_own_sidecars(self):
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 0, r.stderr)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.sidecars()}
        p = self.snapshot(self.fixture_beads([bead("syn-09")]))  # nine open: rejected wholesale
        r = self.run_import(p)
        self.assertEqual(r.returncode, 1)
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.sidecars()}
        self.assertEqual(before, after)


class Mappings(Import):
    def test_mappings_type_prose_baselines_and_triggers(self):
        p = self.snapshot([bead("syn-p1", body=block(baseline="about a third",
                                                     check_when="after the asks settle"))])
        m = self.mappings({"syn-p1": {"baseline": 0.33, "check_when": {"runs": 2, "since": "2026-10-26"}}})
        r = self.run_import(p, mappings=m)
        self.assertEqual(r.returncode, 0, r.stderr)
        loaded = experiments.load_experiments(str(self.repo))["open"]
        self.assertEqual(loaded[0]["baseline"], 0.33)
        self.assertEqual(loaded[0]["check_when"], {"runs": 2, "since": "2026-10-26"})

    def test_mappings_normalize_metric_names_and_created_too(self):
        p = self.snapshot([bead("syn-p1", body=block(metric="tbd metric"))])
        m = self.mappings({"syn-p1": {"metric": "runs per landed bead", "created": "2026-10-28"}})
        r = self.run_import(p, mappings=m)
        self.assertEqual(r.returncode, 0, r.stderr)
        x = experiments.load_experiments(str(self.repo))["open"][0]
        self.assertEqual(x["metric"], "runs_per_landed")
        self.assertEqual(x["created"], "2026-10-28")

    def test_mappings_for_unknown_beads_or_with_unknown_fields_reject(self):
        p = self.snapshot([bead("syn-p1")])
        m = self.mappings({"ghost-1": {"baseline": 1}})
        r = self.run_import(p, mappings=m)
        self.assertEqual(r.returncode, 1)
        self.assertIn("ghost-1, which has no Experiment block", r.stderr)
        m = self.mappings({"syn-p1": {"hypothesis": "a mapping cannot rewrite the block's text"}})
        r = self.run_import(p, mappings=m)
        self.assertEqual(r.returncode, 2)  # the mappings file's shape is broken
        self.assertIn("unknown field(s) hypothesis", r.stderr)
        self.assertIn("metric, baseline, check_when, created", r.stderr)
        self.assertEqual(self.sidecars(), [])

    def test_an_invalid_typed_mapping_value_is_rejected_by_the_shared_contract(self):
        p = self.snapshot([bead("syn-p1")])
        m = self.mappings({"syn-p1": {"check_when": {"runs": 0, "since": "2026-10-26"}}})
        r = self.run_import(p, mappings=m)
        self.assertEqual(r.returncode, 1)
        self.assertIn("syn-p1", r.stderr)
        self.assertEqual(self.sidecars(), [])


class Rerun(Import):
    def test_an_identical_rerun_writes_nothing(self):
        self.assertEqual(self.run_import(FIXTURE).returncode, 0)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.sidecars()}
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("imported 0, unchanged 8, kept 0", r.stdout)
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.sidecars()}
        self.assertEqual(before, after)  # byte-identical, and not even rewritten

    def test_existing_verdicts_are_preserved_and_stay_closed(self):
        self.assertEqual(self.run_import(FIXTURE).returncode, 0)
        experiments.write_verdict(str(self.repo), "syn-03", "keep", "2026-11-01")
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kept", r.stdout)
        self.assertIn("verdict keep 2026-11-01", r.stdout)
        data = json.loads((experiments.sidecar_dir(self.repo) / "syn-03.json").read_text(encoding="utf-8"))
        self.assertEqual(data["verdict"], {"kind": "keep", "date": "2026-11-01"})
        loaded = experiments.load_experiments(str(self.repo))
        self.assertEqual([x["bead"] for x in loaded["closed"]], ["syn-03"])
        self.assertEqual(len(loaded["open"]), 7)
        self.assertIn("open now 7 (cap 8)", r.stdout)  # the kept verdict leaves seven open, not eight

    def test_a_conflicting_different_open_sidecar_is_refused_not_overwritten(self):
        self.assertEqual(self.run_import(FIXTURE).returncode, 0)
        edited = self.seed("syn-05", sidecar(hypothesis="a hand-edited hypothesis, still open",
                                              metric="landed_run1_share", baseline=0.36,
                                              check_when={"date": "2026-11-16"}))
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 1)
        self.assertIn("syn-05: a different open sidecar already exists", r.stderr)
        self.assertIn("not overwritten", r.stderr)
        self.assertIn("a hand-edited hypothesis", edited.read_text(encoding="utf-8"))


class ResultingCap(Import):
    def test_existing_open_sidecars_count_toward_the_resulting_cap(self):
        self.seed("old-1", sidecar())
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 1)
        self.assertIn("would leave 9 experiments open (cap 8)", r.stderr)
        self.assertEqual([p.stem for p in self.sidecars()], ["old-1"])  # the import wrote nothing

    def test_existing_verdicts_do_not_count_toward_the_resulting_cap(self):
        self.seed("old-1", sidecar(verdict={"kind": "revert", "date": "2026-10-20"}))
        r = self.run_import(FIXTURE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.sidecars()), 9)
        loaded = experiments.load_experiments(str(self.repo))
        self.assertEqual(len(loaded["open"]), 8)
        self.assertEqual([x["bead"] for x in loaded["closed"]], ["old-1"])


if __name__ == "__main__":
    unittest.main()
