"""Check rounds that cost less: per-check input cache, cheap-first order, duplicate runs, hang watchdog."""
import json
import os
import shlex
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_engine as te  # noqa: E402
from test_engine import PY, engine  # noqa: E402,F401
import checks_speed as cs  # noqa: E402


class SpeedTest(unittest.TestCase):
    setUp = te.EngineTest.setUp
    tearDown = te.EngineTest.tearDown
    fake_bd = te.EngineTest.fake_bd
    commit_base_cfg = te.EngineTest.commit_base_cfg
    run_engine = te.EngineTest.run_engine
    checks_engine = te.EngineTest.checks_engine

    def bump(self, name="count"):
        n = Path(self.tmp.name) / name
        return PY + ' -c "open(%r, \'a\').write(\'1\')"' % str(n), n

    def notes(self, eng):
        return [json.loads(l).get("text", "") for l in eng.log_path.read_text().splitlines() if '"kind": "note"' in l]


class InputCache(SpeedTest):
    ST = {"checks": [], "files": []}

    def test_a_check_with_inputs_survives_edits_outside_them_and_a_moved_base(self):
        cmd, n = self.bump()
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "inputs": ["client/**"]}])
        (self.wt / "client").mkdir()
        (self.wt / "client" / "a.cs").write_text("1\n")
        eng.run_checks(self.ST, "s")
        (self.wt / "README.md").write_text("doc\n")  # outside the inputs
        te.sh("git", "commit", "--allow-empty", "-qm", "x", cwd=self.wt)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)  # the base moves
        again = eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "1")
        self.assertTrue(again[0]["cached"])
        self.assertTrue(any("cached: unity, inputs unchanged since round 1" in t for t in self.notes(eng)))

    def test_an_edit_inside_the_inputs_or_another_command_reruns(self):
        cmd, n = self.bump()
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "inputs": ["client/**"]}])
        (self.wt / "client").mkdir()
        (self.wt / "client" / "a.cs").write_text("1\n")
        eng.run_checks(self.ST, "s")
        (self.wt / "client" / "a.cs").write_text("2\n")
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "11")
        eng2 = self.checks_engine(checks=[{"id": "unity", "cmd": cmd + " ", "group": "tests", "inputs": ["client/**"]}])
        eng2.run_checks(self.ST, "s")  # same text after whitespace normalisation: still a hit
        self.assertEqual(n.read_text(), "11")
        eng3 = self.checks_engine(checks=[{"id": "unity", "cmd": cmd + " # other", "group": "tests", "inputs": ["client/**"]}])
        eng3.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "111")

    def test_without_inputs_any_untracked_file_still_throws_the_result_away(self):
        cmd, n = self.bump()
        eng = self.checks_engine(checks=[{"id": "t", "cmd": cmd, "group": "tests"}])
        eng.run_checks(self.ST, "s")
        (self.wt / "README.md").write_text("doc\n")
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "11")

    def test_a_red_check_with_inputs_is_not_remembered(self):
        eng = self.checks_engine(checks=[{"id": "t", "cmd": te.FALSE, "group": "tests", "inputs": ["*.txt"]}])
        eng.run_checks(self.ST, "s")
        self.assertFalse(eng.run_checks(self.ST, "s")[0].get("cached"))

    def test_inputs_hash_ignores_files_outside_the_globs(self):
        a = {"x/a": "100644 blob 1", "y/b": "100644 blob 2"}
        b = dict(a, **{"y/b": "100644 blob 3"})
        self.assertEqual(cs.inputs_hash(a, ["x/**"]), cs.inputs_hash(b, ["x/**"]))
        self.assertNotEqual(cs.inputs_hash(a, ["y/**"]), cs.inputs_hash(b, ["y/**"]))
        self.assertEqual(cs.inputs_hash(a, ["z/**"]), "")


class CheapFirst(SpeedTest):
    def slow_then_fast(self):
        mark = Path(self.tmp.name) / "order"
        step = lambda name: PY + ' -c "open(%r, \'a\').write(\'%s \')"' % (str(mark), name)
        return mark, step("slow"), step("quick")

    def seed(self, eng, cmd, secs):
        cs.record_durations(str(self.wt), [(cmd, secs)] * 3, config_dir=os.environ["XDG_CONFIG_HOME"] + "/task-loop")

    def test_the_cheaper_check_runs_first_and_a_red_stops_the_round(self):
        mark, slow, quick = self.slow_then_fast()
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": slow, "group": "tests"},
                                         {"id": "quick", "cmd": quick + "; exit 1", "group": "tests"}])
        self.seed(eng, slow, 400)
        self.seed(eng, quick + "; exit 1", 2)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([c["id"] for c in res], ["quick", "slow"])
        self.assertEqual([c["status"] for c in res], ["failed", "skipped"])
        self.assertEqual(mark.read_text(), "quick ")

    def test_unknown_commands_count_as_cheap_and_durations_are_recorded(self):
        mark, slow, quick = self.slow_then_fast()
        eng = self.checks_engine(checks=[{"id": "known", "cmd": slow, "group": "tests"},
                                         {"id": "new", "cmd": quick, "group": "tests"}])
        self.seed(eng, slow, 90)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([c["id"] for c in res], ["new", "known"])
        hist = cs.load_durations(str(self.wt))
        self.assertEqual(len(hist[cs.norm(quick)]), 1)
        self.assertEqual(len(hist[cs.norm(slow)]), 4)

    def test_a_check_reading_another_checks_log_stays_after_it(self):
        reader = 'test -n "$TL_CHECK_LOG_SLOW"'
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": PY + ' -c "pass"', "group": "tests"},
                                         {"id": "reader", "cmd": reader, "group": "tests"}])
        self.seed(eng, PY + ' -c "pass"', 300)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([(c["id"], c["status"]) for c in res], [("slow", "ran"), ("reader", "ran")])

    def test_order_ignores_sub_five_second_noise(self):
        items = [{"cmd": "a", "g": 0}, {"cmd": "b", "g": 0}]
        hist = {"a": [3.0], "b": [0.1]}
        self.assertEqual([i["cmd"] for i in cs.order_by_cost(items, hist, lambda c: 0)], ["a", "b"])


class Duplicates(SpeedTest):
    def counter(self, code=0):
        n = Path(self.tmp.name) / "unity-runs"
        return PY + ' -c "import sys; open(%r, \'a\').write(\'1\'); print(\'Passed: 12\'); sys.exit(%d)"' % (str(n), code), n

    def test_a_wrapper_that_redirects_the_recipe_reads_the_engines_log_and_runs_only_its_extra_part(self):
        cmd, n = self.counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests"}])
        wrap = "mkdir -p ev && %s > ev/out.log && grep -q 'Passed: 12' ev/out.log" % cmd
        res = eng.run_checks({"checks": [wrap], "files": []}, "s")
        self.assertEqual(n.read_text(), "1")
        self.assertEqual([(c["id"] == "unity-tests", c["status"]) for c in res], [(True, "ran"), (False, "ran")])
        self.assertIn("Passed: 12", (self.wt / "ev" / "out.log").read_text())
        self.assertTrue(any("reuses the log of `unity-tests`" in t for t in self.notes(eng)))

    def test_the_wrappers_extra_part_still_fails_the_round(self):
        cmd, n = self.counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests"}])
        res = eng.run_checks({"checks": ["%s > ev.log && grep -q 'Passed: 99' ev.log" % cmd], "files": []}, "s")
        self.assertEqual((n.read_text(), res[-1]["status"]), ("1", "failed"))

    def test_a_wrapper_that_cannot_be_split_runs_it_and_the_engine_copy_is_skipped(self):
        cmd, n = self.counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests"}])
        res = eng.run_checks({"checks": ["if true; then %s; fi" % cmd], "files": []}, "s")
        self.assertEqual(n.read_text(), "1")
        self.assertEqual([c["status"] for c in res], ["skipped", "ran"])
        self.assertIn("run inside the stage check", res[0]["why"])

    def test_a_red_recipe_ends_the_round_before_the_wrapper(self):
        red, n = self.counter(1)
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": red, "group": "tests"}])
        res = eng.run_checks({"checks": ["%s > ev.log" % red], "files": []}, "s")
        self.assertEqual(([c["status"] for c in res], n.read_text()), (["failed", "skipped"], "1"))

    def test_a_quoted_mention_is_not_a_wrapper(self):
        cmd, n = self.counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests"}])
        res = eng.run_checks({"checks": ["echo %s" % shlex.quote(cmd)], "files": []}, "s")
        self.assertEqual(([c["status"] for c in res], n.read_text()), (["ran", "ran"], "1"))

    def test_reuse_log_keeps_redirections_and_refuses_what_it_cannot_split(self):
        f = cs.reuse_log
        self.assertEqual(f("mkdir -p e && just t > e/o 2>&1 && grep P e/o", "just t", "V"), 'mkdir -p e && cat "$V" > e/o 2>&1 && grep P e/o')
        self.assertEqual(f("just t | tee e/l; grep P e/l", "just t", "V"), 'cat "$V" | tee e/l; grep P e/l')
        self.assertIsNone(f("rm -f r.xml; just t", "just t", "V"))
        self.assertIsNone(f("just t || true", "just t", "V"))
        self.assertIsNone(f("(just t)", "just t", "V"))
        self.assertIsNone(f("just t | grep P", "just t", "V"))

    def gate_run(self, **kw):
        count, seen = Path(self.tmp.name) / "gates", Path(self.tmp.name) / "passed"
        gate = PY + ' -c "import os; open(%r, \'a\').write(os.environ.get(\'TL_CHECKS_GREEN\', \'-\') + \'|\')"' % str(count)
        land = PY + ' -c "import os; open(%r, \'w\').write(os.environ.get(\'TL_GATE_PASSED\', \'\'))" && git push -q origin HEAD:main' % str(seen)
        rc, _ = self.run_engine({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]}, gate=gate, land=land, **kw)
        return rc, count, seen

    def test_the_push_is_told_the_gated_tree_as_a_plain_git_tree_hash(self):
        rc, count, seen = self.gate_run()
        self.assertEqual(rc, 0)
        self.assertEqual(seen.read_text(), te.tl.git("rev-parse", "HEAD^{tree}", cwd=str(self.wt)))

    def test_the_gate_is_told_which_repo_checks_are_green(self):
        rc, count, seen = self.gate_run(checks=[{"id": "ut", "cmd": PY + ' -c "pass"', "group": "tests", "inputs": ["f.txt"]}])
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(count.read_text(), "ut|")

    def test_a_gate_green_on_this_tree_is_not_run_again(self):
        rc, count, seen = self.gate_run()
        self.assertEqual(rc, 0)
        eng = self.eng
        eng.gate_record("abc")
        self.assertTrue(eng.gate_green("abc"))
        self.assertFalse(eng.gate_green("abd"))


class Watchdog(SpeedTest):
    def alive(self, mark):
        return subprocess.run(["pgrep", "-f", "sleep " + mark], capture_output=True, text=True).stdout.strip()

    def test_a_silent_check_is_stopped_as_hung_with_its_last_lines_and_its_tree_is_gone(self):
        mark = "71.%d" % os.getpid()
        n = Path(self.tmp.name) / "tries"
        cmd = "echo started >> %s; echo last words; sleep %s" % (n, mark)
        eng = self.checks_engine(checks=[{"id": "hang", "cmd": cmd, "group": "tests", "retry": 2}], check_idle_min=0.02)
        t = time.time()
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertLess(time.time() - t, 20)
        self.assertEqual((res[0]["status"], res[0]["hung"], res[0]["exit"]), ("failed", True, 124))
        self.assertIn("HUNG", res[0]["tail"])
        self.assertIn("last words", res[0]["tail"])
        self.assertEqual(len(n.read_text().split()), 1)  # never retried
        self.assertEqual(self.alive(mark), "")
        items = [json.loads(l) for l in eng.log_path.read_text().splitlines() if '"kind": "checks"' in l][0]["items"]
        self.assertTrue(items[0]["hung"])

    def test_a_check_that_keeps_printing_is_not_hung(self):
        code = "import time\nfor i in range(5):\n print(i, flush=True); time.sleep(0.6)"
        eng = self.checks_engine(checks=[{"id": "chatty", "cmd": PY + " -c " + shlex.quote(code), "group": "tests"}],
                                 check_idle_min=0.025)  # 1.5 s of silence allowed, 3 s run
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0]["status"], res[0].get("hung")), ("ran", False))

    def test_idle_min_zero_turns_the_watchdog_off_and_a_check_can_set_its_own(self):
        eng = self.checks_engine(checks=[{"id": "q", "cmd": "sleep 2", "group": "tests"}], check_idle_min=0)
        self.assertEqual(eng.run_checks({"checks": [], "files": []}, "s")[0]["status"], "ran")
        eng = self.checks_engine(checks=[{"id": "q", "cmd": "sleep 30", "group": "tests", "idle_min": 0.02}], check_idle_min=0)
        self.assertTrue(eng.run_checks({"checks": [], "files": []}, "s")[0]["hung"])


if __name__ == "__main__":
    unittest.main()
