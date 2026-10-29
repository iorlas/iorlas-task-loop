"""The parallel release gate: the splitter leaves out the serial group, the merge of shard outputs, a crashed shard is red."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402, F401

sys.path.insert(0, str(ROOT / "dev"))
import shard  # noqa: E402

from taskloop.adapters.suiteout import Shard, failure_report, merge_outputs  # noqa: E402
from taskloop.app.release import suite as runner  # noqa: E402

TREE = {
    "test_a.py": "import unittest\nclass A(unittest.TestCase):\n    def test_1(self): pass\n    def test_2(self): pass\n",
    "test_b.py": ("import unittest\nclass B(unittest.TestCase):\n    def test_1(self): pass\nclass C(unittest.TestCase):\n    def "
                  "test_1(self): pass\n"),
    "test_c.py": ("import unittest\nclass D(unittest.TestCase):\n    def test_1(self): pass\n    def test_2(self): pass\n    def "
                  "test_3(self): pass\n"),
}


class Splitter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name, src in TREE.items():
            (self.root / name).write_text(src)
        self.addCleanup(self.tmp.cleanup)
        self.drop_modules()
        self.addCleanup(self.drop_modules)
        sys.path.insert(0, str(self.root))
        self.addCleanup(sys.path.remove, str(self.root))

    @staticmethod
    def drop_modules():
        for m in ("test_a", "test_b", "test_c"):
            sys.modules.pop(m, None)

    def all_ids(self):
        return sorted(t for ids in shard.tests(self.root).values() for t in ids)

    def test_a_serial_entry_leaves_its_tests_out_of_every_shard_and_names_them_in_the_serial_list(self):
        serial = (("test_a", None, "r"), ("test_b", "C", "r"))
        p = shard.plan(2, self.root, serial)
        self.assertEqual(p["serial"], ["test_a.A.test_1", "test_a.A.test_2", "test_b.C.test_1"])
        placed = [t for s in p["shards"] for t in s]
        self.assertEqual(sorted(placed + p["serial"]), self.all_ids())
        self.assertFalse(set(placed) & set(p["serial"]))

    def test_without_serial_every_test_is_in_exactly_one_shard(self):
        placed = [t for s in shard.split(3, self.root) for t in s]
        self.assertEqual(sorted(placed), self.all_ids())

    def test_a_test_entry_takes_only_that_test(self):
        serial = (("test_c", "D.test_2", "r"),)
        p = shard.plan(2, self.root, serial)
        self.assertEqual(p["serial"], ["test_c.D.test_2"])
        self.assertEqual(sorted([t for s in p["shards"] for t in s] + p["serial"]), self.all_ids())

    def test_measured_durations_set_the_balance_and_a_new_test_falls_back_to_its_module_weight(self):
        (self.root / "durations.json").write_text('{"test_a.A.test_1": 100, "test_a.A.test_2": 100, "test_c.D.test_1": 1}')
        load = {}
        shards = shard.split(2, self.root)
        d = shard.load_durations(self.root)
        for i, s in enumerate(shards):
            load[i] = sum(shard.cost(t, d) for t in s)
        self.assertEqual(shard.cost("test_c.D.test_3", d), shard.DEFAULT_WEIGHT)
        self.assertEqual(shard.cost("test_engine.X.test_new", d), shard.DEFAULT_WEIGHT)
        self.assertEqual(shard.cost("test_a.A.test_1", d), 100)
        heavy = next(sh for sh in shards if "test_a.A.test_1" in sh)
        self.assertEqual(sorted(heavy), ["test_a.A.test_1", "test_a.A.test_2"])  # 200 s alone; the rest (5 tests) share the other

    def test_a_class_entry_does_not_take_the_other_classes_of_its_module(self):
        self.assertTrue(shard.is_serial("test_b.C.test_1", (("test_b", "C", "r"),)))
        self.assertFalse(shard.is_serial("test_b.B.test_1", (("test_b", "C", "r"),)))
        self.assertTrue(shard.is_serial("test_b.B.test_1", (("test_b", None, "r"),)))

    def test_the_split_is_stable_and_balanced(self):
        self.assertEqual(shard.split(2, self.root), shard.split(2, self.root))
        self.assertEqual(sorted(len(s) for s in shard.split(2, self.root)), [3, 4])

    def test_every_real_serial_entry_has_a_reason_and_names_a_real_test(self):
        every = [t for ids in shard.tests().values() for t in ids]
        for module, cls, why in shard.SERIAL:
            self.assertTrue(why.strip(), module)
            self.assertTrue(any(shard.is_serial(t, ((module, cls, "r"),)) for t in every), (module, cls))

    def test_the_real_plan_covers_every_test_once(self):
        p = shard.plan(8)
        every = [t for ids in shard.tests().values() for t in ids]
        self.assertEqual(sorted([t for s in p["shards"] for t in s] + p["serial"]), sorted(every))

    def test_the_ids_command_runs_exactly_the_listed_tests_and_records_their_times(self):
        f, times = self.root / "ids.txt", self.root / "times.json"
        f.write_text("test_a.A.test_2\ntest_c.D.test_3\n")
        r = subprocess.run(
            [sys.executable, str(ROOT / "tests" / "shard.py"), "ids", str(f), "--root", str(self.root), "--times", str(times)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ran 2 tests", r.stderr)
        self.assertEqual(sorted(json.loads(times.read_text())), ["test_a.A.test_2", "test_c.D.test_3"])


def ok(n):
    return "." * n + "\n" + "-" * 70 + f"\nRan {n} tests in 1.500s\n\nOK\n"


class Merge(unittest.TestCase):
    def test_green_shards_give_one_total(self):
        out, green = merge_outputs([Shard("s1", 0, ok(3)), Shard("s2", 0, ok(4))], 7)
        self.assertTrue(green)
        self.assertTrue(out.rstrip().endswith("Ran 7 tests in 1.500s\n\nOK"), out)
        self.assertEqual(out.count("Ran "), 1)

    def test_failures_and_errors_add_up_and_their_sections_are_kept(self):
        red = textwrap.dedent("""\
            F.E
            ======================================================================
            FAIL: test_x (m.C.test_x)
            Traceback
            AssertionError: boom

            ======================================================================
            ERROR: test_y (m.C.test_y)
            ValueError: bang

            ----------------------------------------------------------------------
            Ran 3 tests in 0.5s

            FAILED (failures=1, errors=1)
            """)
        out, green = merge_outputs([Shard("s1", 1, red), Shard("s2", 1, red.replace("test_x", "test_p").replace("test_y", "test_q")),
                                            Shard("s3", 0, ok(2))], 8)
        self.assertFalse(green)
        for want in ("FAIL: test_x", "FAIL: test_p", "ERROR: test_q", "AssertionError: boom", "Ran 8 tests in 1.500s",
                     "FAILED (failures=2, errors=2)"):
            self.assertIn(want, out)
        rep = failure_report(out)
        self.assertIn("FAIL: test_p", rep)
        self.assertIn("FAILED (failures=2, errors=2)", rep)

    def test_skips_are_summed_and_stay_green(self):
        out, green = merge_outputs(
            [Shard("s1", 0, ok(2).replace("OK", "OK (skipped=2)")), Shard("s2", 0, ok(1).replace("OK", "OK (skipped=1)"))], 3
        )
        self.assertTrue(green)
        self.assertIn("OK (skipped=3)", out)

    def test_a_shard_that_died_without_a_summary_is_red_and_its_tail_is_shown(self):
        out, green = merge_outputs([Shard("s1", 0, ok(2)), Shard("s2", -9, "starting\nSegmentation fault\n")], 5)
        self.assertFalse(green)
        self.assertIn("ERROR: shard s2 crashed (exit -9)", out)
        self.assertIn("Segmentation fault", out)
        self.assertIn("ERROR: shard s2 crashed", failure_report(out))

    def test_fewer_tests_run_than_planned_is_red(self):
        out, green = merge_outputs([Shard("s1", 0, ok(2))], 3)
        self.assertFalse(green)
        self.assertIn("ERROR: 2 tests ran, 3 were planned", out)

    def test_a_nonzero_exit_with_a_clean_summary_is_red(self):
        _out, green = merge_outputs([Shard("s1", 1, ok(2))], 2)
        self.assertFalse(green)


class Workers(unittest.TestCase):
    def test_default_is_the_smaller_of_cpus_and_ram_over_the_per_shard_budget_never_below_one(self):
        gb = 1024
        cases = ((8, 30 * gb, 8), (8, 6 * gb, 3), (14, 64 * gb, 14), (8, 100, 1), (1, 30 * gb, 1), (4, None, 4), (None, 8 * gb, 1))
        for cpus, mem, want in cases:
            self.assertEqual(runner.host_workers(cpus or 1, mem), want, (cpus, mem))
        env = {k: v for k, v in os.environ.items() if k != "TASK_LOOP_SUITE_WORKERS"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(runner, "available_mb", return_value=5 * gb), \
                mock.patch.object(os, "cpu_count", return_value=8):
            self.assertEqual(runner.workers(), 2)

    def test_available_ram_is_read_from_the_host(self):
        self.assertGreater(runner.available_mb() or 1, 0)

    def test_the_environment_overrides_it(self):
        with mock.patch.dict(os.environ, {"TASK_LOOP_SUITE_WORKERS": "3"}):
            self.assertEqual(runner.workers(), 3)

    def test_a_shard_gets_its_own_home_config_and_temp_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = runner.isolated_env(Path(d) / "a"), runner.isolated_env(Path(d) / "b")
            for k in ("HOME", "XDG_CONFIG_HOME", "TMPDIR"):
                self.assertNotEqual(a[k], b[k])
                self.assertTrue(a[k].startswith(str(Path(d) / "a")))
                self.assertTrue(Path(a[k]).is_dir())


if __name__ == "__main__":
    unittest.main()
