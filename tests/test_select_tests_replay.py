"""The replay checker validates explicit synthetic records and never claims they are history."""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import replay_select_tests as replay  # noqa: E402
import select_tests  # noqa: E402

EVIDENCE = ROOT / ".task" / "tl-7y6.7.25" / "evidence"


def fixture(test_name):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / ("tmp-replay-%s-%d" % (test_name, os.getpid()))
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def landing(order, paths=("unknown/synthetic.txt",), inventory=None, failures=(), errors=(),
            landing_id=None, base=None, landed=None):
    return {
        "id": landing_id or "synthetic-landing-%02d" % order,
        "order": order,
        "base": base or "%040x" % (10000 + order),
        "landed": landed or "%040x" % order,
        "paths": list(paths),
        "inventory": list(inventory or ["test_synthetic.Synthetic.test_ok"]),
        "failures": list(failures),
        "errors": list(errors),
    }


def window(**overrides):
    return [landing(order, **overrides) for order in range(1, replay.WINDOW + 1)]


def real_inventory():
    modules = sorted({module for modules in select_tests.feature_map().values() for module in modules})
    return [module + ".Synthetic.test_ok" for module in modules]


def write_records(path, landings):
    path.write_text(json.dumps({"landings": landings}), encoding="utf-8")


def run_checker(path, *extra):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(ROOT / "dev" / "replay_select_tests.py"), str(path)]
                          + list(extra), cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)


class ValidationTests(unittest.TestCase):
    def test_a_complete_window_is_accepted_in_order(self):
        records = list(reversed(window()))
        valid = replay.validate(records)
        self.assertEqual([item["order"] for item in valid], list(range(1, replay.WINDOW + 1)))

    def test_a_missing_outcome_field_is_rejected(self):
        records = window()
        del records[7]["errors"]
        with self.assertRaisesRegex(replay.RecordError, "errors"):
            replay.validate(records)

    def test_duplicate_landing_identity_or_order_is_rejected(self):
        records = window()
        records[1]["id"] = records[0]["id"]
        with self.assertRaisesRegex(replay.RecordError, "duplicate landing id"):
            replay.validate(records)
        records = window()
        records[1]["order"] = records[0]["order"]
        with self.assertRaisesRegex(replay.RecordError, "duplicate landing order"):
            replay.validate(records)
        records = window()
        records[1]["landed"] = records[0]["landed"]
        with self.assertRaisesRegex(replay.RecordError, "duplicate landing"):
            replay.validate(records)

    def test_landed_sha_duplicates_are_case_insensitive(self):
        records = window()
        records[10]["landed"] = records[9]["landed"].upper()
        with self.assertRaisesRegex(replay.RecordError, "duplicate landing"):
            replay.validate(records)

    def test_an_invalid_inventory_is_rejected(self):
        records = window()
        records[0]["failures"] = ["test_missing.Synthetic.test_fail"]
        with self.assertRaisesRegex(replay.RecordError, "not in the full inventory"):
            replay.validate(records)
        records = window()
        records[0]["inventory"] = ["test_a.Synthetic.test_ok", "test_a.Synthetic.test_ok"]
        with self.assertRaisesRegex(replay.RecordError, "duplicate test ids"):
            replay.validate(records)

    def test_an_incomplete_window_or_gapped_order_is_rejected(self):
        with self.assertRaisesRegex(replay.RecordError, "incomplete 50-landing window"):
            replay.validate(window()[:replay.WINDOW - 1])
        records = [landing(order) for order in range(2, replay.WINDOW + 2)]
        with self.assertRaisesRegex(replay.RecordError, "1..50 without gaps"):
            replay.validate(records)


class ReplayTests(unittest.TestCase):
    features = {"alpha": ["test_a"], "beta": ["test_b"], "gamma": ["test_c"]}
    edges = {"alpha": set(), "beta": set(), "gamma": set()}
    inventory = ["test_a.Synthetic.test_ok", "test_b.Synthetic.test_ok", "test_c.Synthetic.test_ok"]

    def synthetic_window(self, alpha_path):
        records = []
        for order in range(1, 26):
            records.append(landing(order, paths=(alpha_path,), inventory=self.inventory,
                                   failures=("test_a.Synthetic.test_ok",)))
        for order in range(26, 51):
            records.append(landing(order, paths=("unknown/synthetic.txt",), inventory=self.inventory,
                                   failures=("test_a.Synthetic.test_ok",)))
        return records

    def test_known_median_is_reported_and_no_failure_is_missed(self):
        result = replay.replay(self.synthetic_window("skills/task-loop/alpha/planted.py"),
                               features=self.features, edges=self.edges)
        self.assertTrue(result["ok"])
        self.assertAlmostEqual(result["median_share"], 2.0 / 3.0)
        self.assertEqual([item["share"] for item in result["landings"][:25]], [1.0 / 3.0] * 25)
        self.assertEqual([item["share"] for item in result["landings"][25:]], [1.0] * 25)
        self.assertEqual([item["missed"] for item in result["landings"]], [[]] * replay.WINDOW)

    def test_a_planted_missed_failure_is_rejected(self):
        records = [landing(order, paths=("skills/task-loop/alpha/planted.py",),
                           inventory=self.inventory, failures=("test_b.Synthetic.test_fail",))
                   for order in range(1, replay.WINDOW + 1)]
        result = replay.replay(records, features=self.features, edges=self.edges)
        self.assertFalse(result["ok"])
        self.assertEqual(result["median_share"], 1.0 / 3.0)
        self.assertEqual([item["missed"] for item in result["landings"]],
                         [["test_b.Synthetic.test_fail"]] * replay.WINDOW)


class CLITests(unittest.TestCase):
    def test_a_valid_synthetic_window_passes_with_its_median(self):
        path = fixture("valid")
        self.addCleanup(shutil.rmtree, path, True)
        records = window(failures=("test_synthetic.Synthetic.test_ok",))
        write_records(path / "records.json", records)
        proc = run_checker(path / "records.json", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["window"], replay.WINDOW)
        self.assertEqual(result["median_share"], 1.0)

    def test_a_missed_failure_exits_nonzero_and_is_reported(self):
        path = fixture("missed")
        self.addCleanup(shutil.rmtree, path, True)
        inventory = real_inventory()
        records = window(paths=("skills/task-loop/checks/planted.py",), inventory=inventory,
                         failures=("test_tl.Synthetic.test_ok",))
        write_records(path / "records.json", records)
        proc = run_checker(path / "records.json", "--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertFalse(result["ok"])
        self.assertEqual(result["landings"][0]["missed"], ["test_tl.Synthetic.test_ok"])

    def test_an_incomplete_window_exits_nonzero_with_a_message(self):
        path = fixture("incomplete")
        self.addCleanup(shutil.rmtree, path, True)
        write_records(path / "records.json", window()[:49])
        proc = run_checker(path / "records.json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("incomplete 50-landing window", proc.stderr)


class BoundaryTests(unittest.TestCase):
    def test_a_records_path_outside_the_worktree_is_rejected_before_reading(self):
        outside = ROOT.parent / ("synthetic-outside-records-%d.json" % os.getpid())
        proc = run_checker(outside)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("outside the worktree", proc.stderr)

    def test_a_symlink_escaping_the_worktree_is_rejected(self):
        path = fixture("escape")
        self.addCleanup(shutil.rmtree, path, True)
        outside = ROOT.parent / ("synthetic-outside-target-%d.json" % os.getpid())
        link = path / "records.json"
        link.symlink_to(outside)
        proc = run_checker(link)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("outside the worktree", proc.stderr)


if __name__ == "__main__":
    unittest.main()
