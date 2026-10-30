"""Engine tests: the checks round."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import procsim
from support.engine_case import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, EngineTest, no_repo, pid_gone, real_proc, sh

# isort: split
import contextlib
import os
import shlex
import signal
import time
from pathlib import Path
from unittest import mock

from support.briefs import brief_digest, linked_text
from support.builders import cfg_with
from support.checks import res
from support.fakes import as_bead, must_bead
from support.narrow import must
from support.waits import until

from taskloop.adapters import gitrepo
from taskloop.adapters import procs as sproc
from taskloop.adapters.check_probe import PathProbe
from taskloop.app.checks import evidence as check_evidence
from taskloop.app.run import (
    engine,
    entry,
)
from taskloop.app.wire import slots as wslots
from taskloop.contracts import answers
from taskloop.contracts.argv import checks_to_wire
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import WaitWhat
from taskloop.domain import outcome as oc
from taskloop.domain.checks import lint
from taskloop.domain.checks import matchers as check_matchers
from taskloop.domain.checks.writer_split import WriterSplit
from taskloop.domain.review.matchers import Tools
from taskloop.domain.write.matchers import count_tests


class EngineChecksTest(EngineTest):
    def test_repo_checks_on_an_equal_tree_and_base_are_reused(self):
        count = Path(self.tmp.name) / "count"
        bump = procsim.fake("bump", procsim.appends(count))
        eng = self.checks_engine(checks=[{"id": "bump", "cmd": bump, "group": "tests"}])
        st = {"checks": [], "files": []}
        first = eng.run_checks(st, "s")
        again = eng.run_checks(st, "s")
        self.assertEqual(count.read_text(), "1")
        self.assertTrue(again[0].cached)
        (self.wt / "new.txt").write_text("x\n")  # an untracked file changes the tree
        eng.run_checks(st, "s")
        self.assertEqual(count.read_text(), "11")
        self.assertEqual(first[0].exit, 0)

    def test_checks_run_without_the_launchers_claude_session(self):
        c = wslots.load_cfg(str(self.wt))
        eng = engine.Engine("t-1", str(self.wt), c, store=self.store)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "cli"}):
            session_env = procsim.fake("session-env", lambda cwd, env: (1 if env.get("CLAUDE_CODE_ENTRYPOINT") else 0, ""))
            res = eng.run_checks({"checks": [session_env], "files": []}, "s")
        self.assertEqual(res[0].exit, 0)

    def test_checks_run_in_groups_fastest_first_and_stop_at_a_red_group(self):
        eng = self.checks_engine(checks=[{"id": "unit", "cmd": "true", "group": "tests"},
                                         {"id": "lint", "cmd": FALSE, "group": "static"}])
        res = eng.run_checks({"checks": ["true"], "files": []}, "s")
        self.assertEqual([(c.group, c.status) for c in res],
                         [("static", "failed"), ("tests", "skipped"), ("acceptance", "skipped")])
        self.assertIn("static failed", res[1].why)

    def test_a_repo_check_runs_only_when_its_paths_changed(self):
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": "true", "group": "tests", "when": ["client/**"]}])
        eng.git("checkout", "-q", "-b", "task/t-1")
        self.assertEqual(eng.run_checks({"checks": [], "files": []}, "s")[0].status, "skipped")
        (self.wt / "client").mkdir()
        (self.wt / "client" / "a.cs").write_text("x\n")
        self.assertEqual(eng.run_checks({"checks": [], "files": []}, "s")[0].status, "passed")

    def test_a_flaky_check_gets_its_retries(self):
        mark = Path(self.tmp.name) / "seen"

        def red_first(cwd, env):
            first = not mark.exists()
            mark.write_text("")
            return (1 if first else 0), ""
        flaky = procsim.fake("flaky", red_first)
        eng = self.checks_engine(checks=[{"id": "flaky", "cmd": flaky, "group": "tests", "retry": 1}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0].exit, res[0].status, res[0].tries), (0, "passed", 2))

    def sleeping_check(self, secs, counter):
        """A check that counts its runs in `counter` and would take `secs` seconds (the sim stops it at the wall limit, nothing sleeps)."""
        return procsim.fake(f"sleep-{secs}", procsim.takes(secs, then=procsim.appends(counter)))

    def test_a_timed_out_check_is_never_retried(self):
        n = Path(self.tmp.name) / "runs-timeout"
        eng = self.checks_engine(checks=[{"id": "hang", "cmd": self.sleeping_check(30, n), "group": "tests", "retry": 1}],
                                 check_wall_min=0.02)
        with mock.patch.object(eng, "warn") as warn:
            res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0].exit, res[0].tries, n.read_text()), (124, 1, "1"))
        self.assertIn("no retry: timed out after", warn.call_args[0][0])

    def test_exit_124_from_the_command_itself_is_not_retried_either(self):
        n = Path(self.tmp.name) / "runs-124"
        cmd = procsim.fake("exits-124", procsim.appends(n, code=124, out="timeout: the command ran too long"))
        eng = self.checks_engine(checks=[{"id": "t", "cmd": cmd, "group": "tests", "retry": 2}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0].tries, n.read_text()), (1, "1"))

    def test_a_checks_own_wall_min_overrides_the_global_one(self):
        n = Path(self.tmp.name) / "runs-own"
        slow = self.sleeping_check(1.2, n)
        eng = self.checks_engine(checks=[{"id": "short", "cmd": slow, "group": "tests", "wall_min": 0.01}],
                                 check_wall_min=5)
        self.assertEqual(eng.run_checks({"checks": [], "files": []}, "s")[0].exit, 124)
        eng2 = self.checks_engine(checks=[{"id": "long", "cmd": slow, "group": "tests", "wall_min": 0.1}],
                                  check_wall_min=0.01)
        self.assertEqual(eng2.run_checks({"checks": [], "files": []}, "s")[0].exit, 0)

    def test_a_configured_checks_log_and_exit_reach_the_checks_after_it(self):
        cmd, n = self.counting_check("Passed: 12", ok_after=1)
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests"}])
        def reads(cwd, env):
            ok = "Passed: 12" in Path(env["TL_CHECK_LOG_UNITY_TESTS"]).read_text() and env["TL_CHECK_RC_UNITY_TESTS"] == "0"
            return (0 if ok else 1), ""
        read = procsim.fake("reads-the-log TL_CHECK_LOG_UNITY_TESTS TL_CHECK_RC_UNITY_TESTS", reads)
        res = eng.run_checks({"checks": [read], "files": []}, "s")
        self.assertEqual([c.exit for c in res], [0, 0])  # the plan check ran after the repo check and read its log
        self.assertEqual(n.read_text(), "1")

    def test_the_same_command_with_another_timeout_is_one_launch(self):
        cmd, n = self.counting_check("ok", ok_after=1)
        eng = self.checks_engine(checks=[{"id": "a", "cmd": cmd, "group": "static", "wall_min": 1, "cache": False},
                                         {"id": "b", "cmd": cmd, "group": "tests", "wall_min": 2, "cache": False}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((n.read_text(), [bool(c.reused) for c in res]), ("1", [False, True]))

    def test_a_slot_wait_in_a_check_is_read_and_capped_at_its_wall_time(self):
        cmd, _n = self.counting_check("unity-slot: x got slot 0 after 99999999s", ok_after=1)
        eng = self.checks_engine(checks=[{"id": "u", "cmd": cmd, "group": "tests"}])
        eng.run_checks({"checks": [], "files": []}, "s")
        self.assertTrue(0 < eng.waited < 60)
        eng.waits.add(99999999, WaitWhat.SLOT)
        self.assertLessEqual(eng.waited, time.time() - eng.t0)

    def test_budget_min_by_label_raises_the_budget_for_a_labelled_bead(self):
        eng = self.checks_engine(budget_min=5, budget_min_by_label={"unity": 300})
        eng.t0 -= 8 * 60
        self.assertRaises(engine.Blocked, eng.waits.budget_check)
        labelled = self.checks_engine(attrs={"labels": ["unity"]}, budget_min=5, budget_min_by_label={"unity": 300})
        labelled.t0 -= 8 * 60
        labelled.waits.budget_check()

    def test_a_compile_error_amid_library_or_asset_import_lines_is_retried_once(self):
        for ctx in ("Refreshing asset database", "Library/Bee/x.dll locked", "Temp/y missing"):
            self.assertEqual(check_matchers.failure_kind(ctx + "\nA.cs(1,1): error CS1002: ; expected"), "import", ctx)
        cmd, _n = self.counting_check("Library/x\nA.cs(1,1): error CS1002: ; expected")
        eng = self.checks_engine(checks=[{"id": "imp", "cmd": cmd, "group": "tests", "retry": 0}])
        self.assertEqual(eng.run_checks({"checks": [], "files": []}, "s")[0].tries, 2)

    def test_a_locked_editor_is_waited_for_with_backoff_then_passes(self):
        cmd, n = self.counting_check(self.LOCK[0], ok_after=3)
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "retry": 1}])
        with mock.patch.object(eng.checker, "sleep") as sleep:
            res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0].exit, res[0].status, n.read_text()), (0, "passed", "3"))
        self.assertEqual([c[0][0] for c in sleep.call_args_list if c[0][0] >= 15], [15, 30])  # other threads may sleep too

    def test_a_lock_is_waited_for_even_on_a_check_with_no_retry(self):
        cmd, n = self.counting_check(self.LOCK[0], ok_after=2)
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "retry": 0}])
        with mock.patch.object(eng.checker, "sleep"):
            res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0].exit, n.read_text()), (0, "2"))

    @no_repo
    def test_a_passing_check_still_shows_its_notable_lines(self):
        out = check_evidence.compact([res("just check", 0, tail="lane light: ok\nunity steps run: client changed\nfoo\nbar\n439 passed")])
        self.assertIn("unity steps run", out)
        self.assertIn("439 passed", out)

    def test_a_stage_check_always_reruns_it_can_read_state_outside_the_tree(self):
        state = Path(self.tmp.name) / "editor-open"  # a running editor, a log, a bead comment: git cannot see them
        eng = engine.Engine("t-1", str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        gone = procsim.fake(f"editor-closed {state}", lambda cwd, env: (1 if state.exists() else 0, ""))
        st = {"checks": [gone], "files": []}
        self.assertEqual(eng.run_checks(st, "s")[0].exit, 0)
        state.write_text("x")
        again = eng.run_checks(st, "s")
        self.assertEqual(again[0].exit, 1)
        self.assertFalse(again[0].cached)

    def test_a_repo_check_marked_cache_false_always_reruns(self):
        count = Path(self.tmp.name) / "count"
        bump = procsim.fake("bump", procsim.appends(count))
        eng = self.checks_engine(checks=[{"id": "bump", "cmd": bump, "group": "tests", "cache": False}])
        eng.run_checks({"checks": [], "files": []}, "s")
        eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual(count.read_text(), "11")

    def test_a_failed_check_is_never_reused(self):
        count = Path(self.tmp.name) / "count"
        fails = procsim.fake("fails", procsim.appends(count, code=1))
        eng = engine.Engine("t-1", str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        st = {"checks": [fails], "files": []}
        eng.run_checks(st, "s")
        again = eng.run_checks(st, "s")
        self.assertEqual(count.read_text(), "11")
        self.assertFalse(again[0].cached)

    def test_checks_run_without_a_shell(self):
        eng = engine.Engine("t-1", str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        res = eng.run_checks({"checks": [shlex.join(["echo", "$HOME", "&&", "x;", "(y)"])], "files": []}, "s")
        self.assertEqual(res[0].exit, 0, res[0].tail)
        self.assertIn("$HOME && x; (y)", res[0].tail)  # no expansion, no operator: every word reached the program as written

    def test_a_check_that_is_not_an_argv_list_is_refused_with_the_allowed_form(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["test -f f.txt && echo ok"])])
        errs = answers.check("plan", False, bad)
        self.assertEqual(len(errs), 1)
        self.assertIn("stages[0].checks[0]: Expected `array`", errs[0])
        self.assertIn('["just", "name"]', errs[0])
        self.assertEqual(answers.check("plan", False, checks_to_wire(PLAN)), [])

    @real_proc("a stop kills a real child and everything it started")
    def test_a_stop_during_a_check_stops_the_check_and_everything_it_started(self):
        if os.name == "nt":
            self.skipTest("POSIX process groups")
        eng = engine.Engine("t-1", str(self.wt), wslots.load_cfg(str(self.wt)), store=self.store)
        pidfile = Path(self.wt, "child.pid")

        def stopped(*_):  # what the run's SIGTERM handler does, from the same thread, once the check has started its child
            until(lambda: pidfile.exists() and pidfile.read_text().strip(), 5)
            raise engine.Blocked("failed: stopped (SIGTERM)", kind=oc.Kind.PAUSE_KILLED)
        old = signal.signal(signal.SIGALRM, stopped)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        signal.setitimer(signal.ITIMER_REAL, 0.5)
        self.addCleanup(signal.setitimer, signal.ITIMER_REAL, 0)
        with self.assertRaises(engine.Blocked):
            eng.sh(shlex.split(self.spawn(pidfile)))
        child = int(pidfile.read_text())
        if not until(lambda: pid_gone(child), 2.5):
            os.kill(child, 9)
            self.fail("the check's child outlived the stop")

    def test_a_unity_play_mode_test_counts(self):  # lifesim-d5f.59: a [UnityTest] read as tests_added=0
        diff = ("+++ b/client/Assets/Tests/PlayMode/LiveSpeedBarTests.cs\n+        [UnityTest]\n"
                "+        public IEnumerator SpeedButtonsChooseAndLightTheHostSpeed()\n")
        self.assertEqual(count_tests(diff, EngineConfig().test_pattern), (1, 0))

    @no_repo
    def test_tracker_checks_are_told_apart_from_code_that_mentions_bd(self):
        self.assertEqual(lint.tracker_checks(dict(PLAN, risks=[{"what": "x", "check": "env X=1 bd show t-1"}])),
                         ["env X=1 bd show t-1"])
        for ok in (HAS_F, "grep -rn 'bd list' src", "pytest tests/test_bd.py", "test -f abd"):
            self.assertEqual(lint.tracker_checks(dict(PLAN, risks=[{"what": "x", "check": ok}])), [], ok)

    def test_a_write_prompt_names_each_check_command_once_in_its_may_run_lists(self):
        # tl-7y6.6.12: the stage's checks and the where() text both listed "You may run these"
        cmd = procsim.fake("print-1", procsim.exits(0, "1"))
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[cmd, HAS_F])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]},
                                raw={"checks": [{"id": "x", "cmd": cmd, "group": "static"}, {"id": "y", "cmd": "echo only-repo"}]})
        self.assertEqual(rc, 0, self.blocked)
        w = next(p for (c, p) in zip(s.calls, s.prompts, strict=False) if c[0] == "worker")
        may = w[w.index("The stage's checks"):w.index("A check that mentions")]
        self.assertEqual(may.count(cmd), 1)
        self.assertEqual(may.count(HAS_F), 1)
        self.assertEqual(may.count("only-repo"), 1)

    def test_a_sleeping_check_is_cut_at_check_wall_min_not_node_timeout_min(self):
        eng = self.checks_engine(check_wall_min=0.01, node_timeout_min=45)
        res = eng.run_checks({"checks": [procsim.fake("sleep-30", procsim.takes(30))], "files": []}, "s")
        self.assertEqual((res[0].exit, res[0].status), (124, "failed"))
        self.assertIn("timed out after 0.01 min", res[0].tail)

    @real_proc("a SIGTERM to the engine kills a real child and its tree")
    def test_sigterm_during_a_stage_check_stops_its_tree_and_still_closes(self):
        pidfile = Path(self.tmp.name, "child.pid")
        check = self.spawn(pidfile, term=True)
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[check])])
        with self.stoppable():
            rc, _ = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertIn("stopped (SIGTERM)", self.said())
        self.assertDead(self.child_of(pidfile))
        self.assertIn("wip (t-1)", gitrepo.git("log", "-1", "--format=%s", "task/t-1", cwd=str(self.wt)))

    def test_fresh_drops_the_checkpoint(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, fresh=True)
        self.assertEqual(rc, 0)
        self.assertEqual(s.calls[0][0], "planner")
        self.assertNotIn("already accepted", s.prompts[0])

    def test_a_tree_changed_since_the_checkpoint_starts_over(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)  # a parked slot is left detached at the base
        (self.wt / "f.txt").write_text("someone edited it\n")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(s.calls[0][0], "planner")
        self.assertIn("changed since", self.eng.log_path.read_text())

    def test_a_slow_check_is_the_engines_and_a_fast_failed_check_is_the_writers_to_rerun(self):
        slow = "true unity-tests"
        fast = procsim.fake("red-on-d2 fast-one", lambda cwd, env: (1 if procsim.f_txt(cwd) == "d2" else 0, ""))
        rc, s = self.run_engine({"plan": [self.plan_with(slow, fast)], "write": [WRITE, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        first, again = s.prompts[1], s.prompts[2]
        self.assertIn("The engine runs these, do not run them:\n- " + slow, first)
        self.assertIn("You may run these:\n- " + fast, first)
        self.assertIn("never start a command you expect to take over a minute; never poll a running command more than 3 times",
                      first.replace("Never", "never"))
        you_may = again[again.index("Only the failed checks"):]
        self.assertIn("You may run these:\n- " + fast, you_may)
        self.assertNotIn("- " + slow, you_may.split("You may run these:")[1].split("If a command")[0])
        self.assertNotIn("do not run them:\n- " + slow, again)

    @no_repo
    def test_a_check_is_engine_only_by_its_last_duration_else_by_its_name(self):
        def only(cmd, secs):
            return WriterSplit(cfg_with(writer_check_max_s=60), secs).engine_only(cmd)
        self.assertTrue(only("just lint", {"just lint": 61}))
        self.assertFalse(only("just unity-tests", {"just unity-tests": 60}))
        self.assertTrue(only("just play-tests", {}))
        self.assertTrue(only("just test-all", {}))
        self.assertFalse(only("just display", {}))

    def test_a_brief_the_owner_changed_or_a_checkpoint_without_writer_seen_gets_the_full_prompt(self):
        _rc, _s = self.two_writes(ctx_k=40)
        args = (1, "g", "f.txt", "", "checks", "where", "fb", "")
        self.assertIn("The brief is unchanged", must(self.eng.hand.delta(*args)))
        (self.eng.run_dir / "brief.md").write_text("the owner answered: use X\n")  # an answer came in
        self.assertIsNone(self.eng.hand.delta(*args))
        (self.eng.run_dir / "brief.md").write_text(self.eng.brief_file.read_text())
        self.eng.writer["seen"] = None  # a checkpoint of before this existed
        self.assertIsNone(self.eng.hand.delta(*args))

    @no_repo
    def test_a_tool_counts_only_backticked_or_after_a_run_verb(self):
        self.assertEqual(Tools.named("`UseCellBeside` handles a rotated slot; `justfile` has the recipe"), [])
        self.assertEqual(Tools.named("nobody ran `shellcheck -x hooks/*.sh` or linted with ruff"),
                         ["shellcheck", "ruff"])
        self.assertEqual(Tools.named("the biome transition fades in; no black screen between lots"), [])
        self.assertEqual(Tools.named("`mypy` was not run; nobody checked with eslint"), ["mypy", "eslint"])

    def test_run_task_refuses_the_main_checkout(self):
        a = mock.Mock(id="t-1", worktree=str(self.wt), slot=None, dry_run=True, fresh=False, quiet=True, outcome_file=None)
        with mock.patch.object(entry, "Engine") as made, contextlib.chdir(self.wt):
            rc = entry.main(a, self.store)
        self.assertEqual(rc, 1)
        made.assert_not_called()

    def test_dry_check_reads_the_argv_not_a_shell_string(self):
        def plan(*checks, files=("new.txt",)):
            return dict(PLAN, stages=[dict(PLAN["stages"][0], checks=list(checks), files=list(files))])
        wt = PathProbe(self.wt, sproc.current_env())
        self.assertEqual(lint.dry_check(plan("test -f a.txt", "test -f new.txt", "grep -q '<(' a.txt", HAS_F), wt), [])
        self.assertEqual(lint.dry_check(plan("test -f $HOME/x", "cat dir/*.txt"), wt), [])  # no shell: a plain word, not judged as a path
        self.assertEqual(lint.dry_check(plan("python3 -m pytest -q tests", "python3 -c pass"), wt), [])
        self.assertTrue(lint.dry_check(plan("python3 tests/nope.py"), wt))
        self.assertTrue(lint.dry_check(plan("test -f missing.txt"), wt)[0].count("missing.txt"))
        self.assertIn("is not an executable here", lint.dry_check(plan("After building the player: python3 x.py"), wt)[0])
        for operator in ("&&", "||", "|", ";", ">", "2>&1"):
            self.assertIn("literal argument in an argv", lint.dry_check(plan(shlex.join(["echo", "a", operator, "b"])), wt)[0], operator)
        self.assertIn("string command again", lint.dry_check(plan(shlex.join(["bash", "-c", "true"])), wt)[0])
        self.assertIn("string command again", lint.dry_check(plan(shlex.join(["/bin/sh", "-lc", "true"])), wt)[0])
        if os.name != "nt":  # lint.dry_check compares os.path.normpath'd stage files with the check's "src/new.txt"
            self.assertEqual(lint.dry_check(plan("test -f src/new.txt", files=("src/",)), wt), [])

    @no_repo
    def test_linked_beads_are_at_most_ten_and_never_change_the_checkpoint_hash(self):
        names = " ".join(f"t-{k}" for k in range(20, 40))
        bead = dict(BEAD, description=names)
        def show(b, cwd=None):
            return {"id": b, "title": "T" + b, "status": "closed", "close_reason": "r"}
        out = linked_text("t-1", must_bead(bead), [], lambda b: as_bead(show(b)), lambda b: [])
        self.assertEqual(out.count("\n- t-"), 10)
        a = brief_digest(must_bead(bead), [], owner_only=True)
        self.assertNotIn("Linked beads", a)
