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
from checks import lint  # noqa: E402
from checks import speed as cs  # noqa: E402


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

    @property
    def eng_tree(self):
        return self.checks_engine()

    def test_a_check_with_inputs_survives_edits_outside_them_and_a_moved_base(self):
        cmd, n = self.bump()
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "inputs": ["client/**"], "inputs_only": True}])
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

    def test_the_justfile_a_lockfile_the_base_and_the_env_are_inputs_unless_inputs_only(self):
        cmd, n = self.bump()
        chk = {"id": "u", "cmd": cmd, "group": "tests", "inputs": ["client/**"]}
        eng = self.checks_engine(checks=[chk])
        (self.wt / "client").mkdir()
        (self.wt / "client" / "a.cs").write_text("1\n")
        eng.run_checks(self.ST, "s")
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "1")
        (self.wt / "justfile").write_text("x:\n")  # outside the globs, but it defines the recipe
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "11")
        (self.wt / "packages-lock.json").write_text("{}")
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "111")
        te.sh("git", "commit", "--allow-empty", "-qm", "x", cwd=self.wt)
        te.sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)  # the base moves
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "1111")
        eng2 = self.checks_engine(checks=[dict(chk, env={"A": "1"})])
        eng2.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "11111")

    def test_a_gitignored_file_under_the_globs_counts_by_its_content(self):
        cmd, n = self.bump()
        (self.wt / ".gitignore").write_text("*.bin\n")
        eng = self.checks_engine(checks=[{"id": "u", "cmd": cmd, "group": "tests", "inputs": ["gen/**"], "inputs_only": True}])
        (self.wt / "gen").mkdir()
        (self.wt / "gen" / "t.txt").write_text("1\n")  # a tracked file keeps the glob alive
        (self.wt / "gen" / "o.bin").write_text("1\n")
        eng.run_checks(self.ST, "s")
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "1")
        (self.wt / "gen" / "o.bin").write_text("2\n")
        eng.run_checks(self.ST, "s")
        self.assertEqual(n.read_text(), "11")

    def test_one_glob_matches_tracked_and_ignored_files_alike(self):
        names = ["client/App/a", "client/App/sub/b", "client/Core/c", "client/Other/d", "client/e"]
        tracked = {n + ".cs": "100644 blob 1" for n in names}
        (self.wt / ".gitignore").write_text("*.gen\n")
        for n in names:
            (self.wt / (n + ".gen")).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / (n + ".gen")).write_text("x")
        for g in ("client/*/*.X", "client/**/*.X", "client/*.X", "client/{App,Core}/**", "client/{App,Core}/*.X", "client/**"):
            t_ = {p[:-3] for p in tracked if cs.inputs_hash({p: tracked[p]}, [g.replace("X", "cs")])}
            i_ = {p[:-4] for p in cs.ignored_paths(str(self.wt), [g.replace("X", "gen")])}
            self.assertEqual(t_, i_, g)
        self.assertEqual({p[:-4] for p in cs.ignored_paths(str(self.wt), ["client/*/*.gen"])}, {"client/App/a", "client/Core/c", "client/Other/d"})
        self.assertEqual({p[:-4] for p in cs.ignored_paths(str(self.wt), ["client/{App,Core}/**"])}, {"client/App/a", "client/App/sub/b", "client/Core/c"})

    def test_the_ignored_walk_is_cut_to_the_globs_folders_and_the_excluded_ones(self):
        seen = []
        real = cs.subprocess.run
        cs.subprocess.run = lambda args, **kw: (seen.append(args), real(args, **kw))[1]
        try:
            cs.ignored_paths(str(self.wt), ["client/Assets/{App,Core}/**"], ["client/Assets/App/*/Gen/**"])
        finally:
            cs.subprocess.run = real
        spec = " ".join(seen[0])
        self.assertIn(":(literal)client/Assets/App/", spec)
        self.assertIn(":(literal)client/Assets/Core/", spec)
        self.assertIn(":(exclude,glob)client/Assets/App/*/Gen/**", spec)
        self.assertNotIn("Library", spec)

    def test_excluded_paths_do_not_change_the_key_tracked_or_ignored(self):
        (self.wt / ".gitignore").write_text("*.gen\n")
        (self.wt / "client" / "Gen").mkdir(parents=True)
        (self.wt / "client" / "a.cs").write_text("1\n")
        (self.wt / "client" / "Gen" / "t.cs").write_text("1\n")
        (self.wt / "client" / "Gen" / "i.gen").write_text("1\n")
        c = {"cmd": "x", "inputs": ["client/**"], "inputs_only": True, "exclude": ["client/Gen/**"]}

        def key():
            return cs.InputKeys(str(self.wt), self.tree(), "b").key(c)
        k = key()
        (self.wt / "client" / "Gen" / "i.gen").write_text("2\n")  # an excluded ignored file
        (self.wt / "client" / "Gen" / "t.cs").write_text("2\n")  # an excluded tracked (here: untracked-new) file
        self.assertEqual(key(), k)
        (self.wt / "client" / "a.cs").write_text("2\n")
        self.assertNotEqual(key(), k)
        self.assertNotEqual(cs.InputKeys(str(self.wt), self.tree(), "b").key(dict(c, exclude=[])), key())

    def tree(self):
        return self.eng_tree.tree_hash()

    def test_a_glob_that_matches_no_tracked_file_switches_the_cache_off(self):
        cmd, n = self.bump()
        (self.wt / "client").mkdir()
        (self.wt / "client" / "a.cs").write_text("1\n")
        for globs in (["client/**", "clent/**"], ["client/{a,b}.cs", "src/**/*.cs"]):
            n.write_text("")
            eng = self.checks_engine(checks=[{"id": "u", "cmd": cmd, "group": "tests", "inputs": globs}])
            eng.run_checks(self.ST, "s")
            again = eng.run_checks(self.ST, "s")
            self.assertEqual(n.read_text(), "11", globs)  # one dead glob is enough
            self.assertFalse(again[0].get("cached"))

    def test_doctor_reports_a_dead_inputs_glob(self):
        (self.wt / "a.cs").write_text("1\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "a", cwd=self.wt)
        (self.wt / ".task-loop.json").write_text(json.dumps({"engine": {"checks": [
            {"id": "u", "cmd": "x", "inputs": ["*.cs"]}, {"id": "v", "cmd": "y", "inputs": ["client/{A,B}/**"]}]}}))
        te.sh("git", "add", ".task-loop.json", cwd=self.wt)
        te.sh("git", "commit", "-qm", "doctor config", cwd=self.wt)
        te.sh("git", "update-ref", "refs/remotes/origin/main", "HEAD", cwd=self.wt)
        warns = engine.tl.doctor_warnings(str(self.wt))
        self.assertEqual(len([w for w in warns if "matches no tracked file" in w]), 1)
        self.assertIn("client/{A,B}/**", " ".join(warns))

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

    @te.POSIX_CHECK
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

    def test_cheap_checks_all_run_before_the_stop_and_only_green_runs_are_recorded(self):
        mark, slow, quick = self.slow_then_fast()
        red = FALSE_P = te.FALSE
        eng = self.checks_engine(checks=[{"id": "a", "cmd": red, "group": "tests"}, {"id": "b", "cmd": quick, "group": "tests"},
                                         {"id": "c", "cmd": slow, "group": "tests"}])
        self.seed(eng, slow, 400)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([(c["id"], c["status"]) for c in res], [("a", "failed"), ("b", "ran"), ("c", "skipped")])
        hist = cs.load_durations(str(self.wt))
        self.assertNotIn(cs.norm(red), hist)
        self.assertIn(cs.norm(quick), hist)

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

    @te.POSIX_CHECK
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

    @te.POSIX_CHECK
    def test_no_wrapper_pattern_that_is_not_the_bare_command_skips_the_repo_check(self):
        n = Path(self.tmp.name) / "runs"
        (self.wt / "t.sh").write_text("echo x >> %s\necho 'Passed: 12'\n" % n)
        cmd = "sh t.sh"
        wrappers = ["sh t.sh foo", "FOO=1 sh t.sh", "sh t.sh || true", "! sh t.sh || true", "if true; then sh t.sh; fi", "(sh t.sh)",
                    "sh t.sh; true", "rm -f z.log; sh t.sh > z.log", "echo 'sh t.sh'", "sh t.sh | grep P", "sh t.sh & wait"]
        for w in wrappers:
            n.write_text("")
            eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests", "cache": False}])
            res = eng.run_checks({"checks": [w], "files": []}, "s")
            self.assertEqual(res[0]["status"], "ran", w)  # the repo check always runs
            if "echo 'sh" not in w:
                self.assertEqual(len(n.read_text().split()), 2, w)  # and the wrapper runs its own copy as written

    def test_a_wrapper_is_split_only_when_the_extra_part_reads_nothing_but_the_log(self):
        (self.wt / "other.xml").write_text("x\n")
        for extra, ok in (("grep -q 'Passed: 12' o.log", True), ("grep -q Passed other.xml", False), ("grep -q Passed $(ls)", False),
                          ("python3 check.py o.log", False), ("grep -q Passed ./o.log", False)):
            self.assertEqual(bool(cs.reuse_log("sh t.sh > o.log && " + extra, "sh t.sh", "V", str(self.wt))), ok, extra)

    def test_a_wrapper_runs_in_full_when_the_repo_check_is_cached_without_a_log_or_skipped(self):
        cmd, n = self.counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests", "when": ["nothing/**"]}])
        wrap = "%s > ev.log && grep -q 'Passed: 12' ev.log" % cmd
        res = eng.run_checks({"checks": [wrap], "files": []}, "s")
        self.assertEqual(([c["status"] for c in res], n.read_text()), (["skipped", "ran"], "1"))

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
        self.assertEqual(f("just t | tee e/l && grep P e/l", "just t", "V"), 'cat "$V" | tee e/l && grep P e/l')
        self.assertIsNone(f("just t | tee e/l; grep P e/l", "just t", "V"))
        self.assertIsNone(f("rm -f r.xml && just t", "just t", "V"))
        self.assertIsNone(f("cd client && just t > o && grep P o", "just t", "V"))
        self.assertIsNone(f("just t foo", "just t", "V"))
        self.assertIsNone(f("FOO=1 just t", "just t", "V"))
        self.assertIsNone(f("! just t", "just t", "V"))
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


class Schedule(SpeedTest):
    """tl-7y6.7.11 / .7 / .16 (R09): one launch per command, Unity last, the ban on Unity in acceptance."""
    # yxbb.3-20261025-005743 engine-checks.r1.json, from ~/.config/task-loop/runs (read-only): the repo checks of lifesim's
    # .task-loop.json (timeout_min 30 on the two test checks) and the round's items with the seconds they took.
    REPO = [{"id": "fmt", "cmd": "just fmt-check-changed", "group": "static"}, {"id": "text", "cmd": "just text", "group": "static"},
            {"id": "unity-analyzers", "cmd": "just unity-analyzers", "group": "static"},
            {"id": "unity-tests", "cmd": "just unity-tests", "group": "tests", "timeout_min": 30},
            {"id": "unity-play-tests", "cmd": "just unity-play-tests", "group": "tests", "timeout_min": 30}]
    GREP = ('test "${TL_CHECK_RC_UNITY_PLAY_TESTS:?}" -eq 0 && test -r "${TL_CHECK_LOG_UNITY_PLAY_TESTS:?}" && grep -Eq '
            "'total=[1-9][0-9]* passed=[1-9][0-9]* failed=0 skipped=0' \"$TL_CHECK_LOG_UNITY_PLAY_TESTS\"")
    R1 = {"just fmt-check-changed": 2, "just text": 0, "just worker-plan": 0, "python3 tools/select_tests.py --phase coordinator": 0,
          "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.tests.test_select_tests": 0,
          "dotnet csharpier check ./client/Assets/Tests/PlayMode/ShareableLoopTests.cs": 1, "just text theme-check client-layers": 1,
          "just unity-analyzers": 104, "just unity-tests": 190, "just unity-play-tests": 571, GREP: 0}
    ACCEPTANCE_R1 = ["just worker-plan", "python3 tools/select_tests.py --phase coordinator",
                     "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.tests.test_select_tests",
                     "dotnet csharpier check ./client/Assets/Tests/PlayMode/ShareableLoopTests.cs", "just text theme-check client-layers",
                     "just unity-analyzers", "just unity-tests", "just unity-play-tests", GREP,
                     "just unity-play-tests", "just unity-play-tests", "just unity-play-tests"]

    def replay(self, repo, accept, secs, red=(), **cfg):
        """Run one check round with a fake shell: no process starts; each launch costs secs[cmd] simulated seconds.
        Returns (results, [launched commands], simulated seconds per result id)."""
        eng = self.checks_engine(checks=repo, **cfg)
        launched = []

        def fake(cmd, timeout=3600, check=False, save=None, env=None, pin=False, idle=0):
            if not isinstance(cmd, str):
                return real(cmd, timeout=timeout, check=check, save=save, env=env, pin=pin, idle=idle)
            launched.append(cmd)
            eng.hung = False
            if save:
                Path(save).write_text("ran %s\n" % cmd)
            return (1 if cmd in red else 0), "ran"
        real = eng.sh
        eng.sh = fake
        res = eng.run_checks({"checks": accept, "files": []}, "s")
        return res, launched, {i: secs.get(c["cmd"], 0) if c.get("log") else 0 for i, c in enumerate(res)}

    def test_a_plan_copy_with_a_longer_limit_than_the_repo_check_is_one_launch(self):
        cmd, n = self.counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests", "timeout_min": 30, "cache": False}])
        res = eng.run_checks({"checks": [cmd], "files": []}, "s")  # the plan's copy gets check_timeout_min, 60
        self.assertEqual(eng.cfg["check_timeout_min"], 60)
        self.assertEqual((n.read_text(), [bool(c.get("reused")) for c in res]), ("1", [False, True]))

    def counter(self, code=0):
        n = Path(self.tmp.name) / "unity-runs"
        return PY + ' -c "import sys; open(%r, \'a\').write(\'1\'); print(\'Passed: 12\'); sys.exit(%d)"' % (str(n), code), n

    @te.POSIX_CHECK
    def test_a_wrapper_that_only_sets_up_and_redirects_is_the_repo_check(self):
        cmd, n = self.counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests", "cache": False}])
        res = eng.run_checks({"checks": ["mkdir -p e && %s > e/log 2>&1" % cmd], "files": []}, "s")
        self.assertEqual((n.read_text(), [c["status"] for c in res]), ("1", ["ran", "ran"]))
        self.assertEqual(cs.canon("mkdir -p e && just unity-tests > e/log"), "just unity-tests")
        self.assertEqual(cs.canon("just   unity-tests  | tee -a e/log"), "just unity-tests")
        for kept in ("FOO=1 just unity-tests", "just unity-tests foo", "cd client && just unity-tests", "just unity-tests; true",
                     "mkdir e && just a && just b", "! just unity-tests"):
            self.assertEqual(cs.canon(kept), " ".join(kept.split()), kept)

    def test_a_first_run_that_timed_out_under_a_shorter_limit_is_not_reused_by_a_longer_one(self):
        n = Path(self.tmp.name) / "slow-runs"
        slow = PY + ' -c "import time; open(%r, \'a\').write(\'1\'); time.sleep(3)"' % str(n)
        eng = self.checks_engine(checks=[{"id": "short", "cmd": slow, "group": "tests", "timeout_min": 0.02, "cache": False},
                                         {"id": "long", "cmd": slow, "group": "tests", "timeout_min": 1, "cache": False}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual(([c["exit"] for c in res], n.read_text()), ([124, 0], "11"))

    def test_replay_yxbb3_r1_the_acceptance_copies_of_the_unity_checks_add_nothing(self):
        res, launched, secs = self.replay(self.REPO, self.ACCEPTANCE_R1, self.R1, cache=True)
        for c in ("just unity-analyzers", "just unity-tests", "just unity-play-tests"):
            self.assertEqual(launched.count(c), 1, c)  # r1 launched unity-tests and unity-play-tests twice
        copies = [r for r in res if r["group"] == "acceptance" and r["cmd"].startswith("just unity-")]
        self.assertEqual(len(copies), 6)  # the analyzers, unity-tests and four play-test copies, as in r1
        self.assertTrue(all(r.get("reused") for r in copies))
        # r1 as recorded spent 869 s on the repo checks plus 208 s (unity-tests) and 536 s (unity-play-tests) on acceptance copies
        self.assertEqual(sum(self.R1[c] for c in launched), 869)

    def test_acceptance_that_reads_no_check_log_is_judged_before_the_unity_group(self):
        repo = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"}, {"id": "fmt", "cmd": "just fmt", "group": "static"}]
        res, launched, _ = self.replay(repo, ["just cheap-accept", "test -r $TL_CHECK_LOG_UNITY_TESTS"], {})
        self.assertEqual(launched, ["just fmt", "just cheap-accept", "just unity-tests", "test -r $TL_CHECK_LOG_UNITY_TESTS"])

    def test_a_red_acceptance_check_stops_the_round_before_unity_with_the_reason(self):
        repo = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"},
                {"id": "unity-analyzers", "cmd": "just unity-analyzers", "group": "static"}]
        accept = ["just cheap-accept", "test -r $TL_CHECK_LOG_UNITY_TESTS", "just unity-tests"]
        res, launched, _ = self.replay(repo, accept, {}, red={"just cheap-accept"})
        self.assertEqual(launched, ["just cheap-accept"])
        skipped = [(c["id"], c["why"]) for c in res if c["status"] == "skipped"]
        self.assertEqual(len(skipped), 4)
        self.assertTrue(all("failed first" in w for _, w in skipped))

    def test_replay_of_acceptance_only_red_rounds_never_relaunches_unity(self):
        # a round shaped like yxbb.3 r1 whose only red is a cheap acceptance check, replayed three times (the rounds a writer fixes)
        for bad in ("just worker-plan", "just text theme-check client-layers", "python3 tools/select_tests.py --phase coordinator"):
            res, launched, _ = self.replay(self.REPO, self.ACCEPTANCE_R1, self.R1, red={bad}, cache=True)
            self.assertFalse([c for c in launched if "unity" in c], bad)
            self.assertEqual([c["id"] for c in res if c["status"] == "failed"], [bad])

    def test_the_plan_validator_rejects_unity_recipes_in_acceptance_and_a_limit_above_the_cap(self):
        cfg = {"checks": self.REPO}
        plan = dict(te.PLAN, stages=[dict(te.PLAN["stages"][0], checks=[
            "just unity-tests", "mkdir -p e && just unity-play-tests > e/log && grep -q ok e/log", "echo 'just unity-tests'", "just unity-foo", "just fmt"])])
        got = lint.unity_problems(plan, cfg)
        self.assertEqual(len(got), 3)
        self.assertIn("TL_CHECK_LOG_UNITY_TESTS", got[0])
        self.assertIn("TL_CHECK_RC_UNITY_PLAY_TESTS", got[1])
        self.assertIn("do not launch it from acceptance", got[2])
        over = dict(te.PLAN, stages=[dict(te.PLAN["stages"][0], checks=["just play --timeout_ms 7200000"])])
        self.assertEqual(len(lint.timeout_problems(over, 60)), 1)
        self.assertEqual(lint.repo_check_of("mkdir -p e && just unity-tests > e/log", cfg), "unity-tests")
        self.assertIsNone(lint.repo_check_of("just unity-tests foo", cfg))


class Watchdog(SpeedTest):
    def alive(self, mark):
        return subprocess.run(["pgrep", "-f", "sleep " + mark], capture_output=True, text=True).stdout.strip()

    @te.POSIX_CHECK
    def test_a_silent_check_is_stopped_as_hung_with_its_last_lines_and_its_tree_is_gone(self):
        mark = "71.%d" % os.getpid()
        n = Path(self.tmp.name) / "tries"
        cmd = "echo started >> %s; echo last words; sleep %s" % (n, mark)
        eng = self.checks_engine(checks=[{"id": "hang", "cmd": cmd, "group": "tests", "retry": 2}], check_idle_min=0.02)
        t = time.time()
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertLess(time.time() - t, 60)  # hang guard only: below the 71 s sleep, so waiting it out fails; the hung/124/tree-gone asserts below are the real gate
        self.assertEqual((res[0]["status"], res[0]["hung"], res[0]["exit"]), ("failed", True, 124))
        self.assertIn("HUNG", res[0]["tail"])
        self.assertIn("last words", res[0]["tail"])
        self.assertEqual(len(n.read_text().split()), 1)  # never retried
        self.assertEqual(self.alive(mark), "")
        items = [json.loads(l) for l in eng.log_path.read_text().splitlines() if '"kind": "checks"' in l][0]["items"]
        self.assertTrue(items[0]["hung"])

    def test_a_check_that_keeps_printing_is_not_hung(self):
        code = "import time\nfor i in range(5):\n print(i, flush=True); time.sleep(0.6)"
        eng = self.checks_engine(checks=[{"id": "chatty", "cmd": PY + " -c " + te.shq(code), "group": "tests"}],
                                 check_idle_min=0.025)  # 1.5 s of silence allowed, 3 s run
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0]["status"], res[0].get("hung")), ("ran", False))

    def test_a_check_writing_a_file_under_the_worktree_without_printing_is_not_hung(self):
        code = "import time\nfor i in range(7):\n open('out.log','a').write('x'*50); time.sleep(0.6)"
        eng = self.checks_engine(checks=[{"id": "w", "cmd": PY + " -c " + te.shq(code), "group": "tests"}], check_idle_min=0.03)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0]["status"], res[0].get("hung")), ("ran", False))

    def test_a_check_burning_cpu_without_output_or_files_is_not_hung(self):
        code = "import time\nt=time.time()\nwhile time.time()-t<5: sum(range(10000))"
        eng = self.checks_engine(checks=[{"id": "cpu", "cmd": PY + " -c " + te.shq(code), "group": "tests"}], check_idle_min=0.03)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0]["status"], res[0].get("hung")), ("ran", False))

    def test_the_hang_notice_names_all_three_signals(self):
        eng = self.checks_engine(checks=[{"id": "h", "cmd": "sleep 30", "group": "tests"}], check_idle_min=0.02)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertIn("no output, file writes or CPU", res[0]["tail"])

    @te.POSIX_CHECK
    def test_a_timeout_keeps_the_output_and_kills_a_setsid_descendant(self):
        mark = "72.%d" % os.getpid()
        code = "import os,subprocess,sys,time\nprint('before', flush=True)\nsubprocess.Popen(['sleep','%s'], start_new_session=True)\ntime.sleep(30)" % mark
        eng = self.checks_engine(checks=[{"id": "t", "cmd": PY + " -c " + te.shq(code), "group": "tests", "timeout_min": 0.05}],
                                 check_idle_min=5)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual(res[0]["exit"], 124)
        self.assertIn("before", (Path(eng.run_dir) / res[0]["log"]).read_text())
        time.sleep(1)
        self.assertEqual(self.alive(mark), "")

    def test_idle_min_zero_turns_the_watchdog_off_and_a_check_can_set_its_own(self):
        eng = self.checks_engine(checks=[{"id": "q", "cmd": "sleep 2", "group": "tests"}], check_idle_min=0)
        self.assertEqual(eng.run_checks({"checks": [], "files": []}, "s")[0]["status"], "ran")
        eng = self.checks_engine(checks=[{"id": "q", "cmd": "sleep 30", "group": "tests", "idle_min": 0.02}], check_idle_min=0)
        self.assertTrue(eng.run_checks({"checks": [], "files": []}, "s")[0]["hung"])


if __name__ == "__main__":
    unittest.main()
