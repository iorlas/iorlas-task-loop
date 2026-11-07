"""Whole beads through the Engine, moved out of tests/checks/test_engine_checks.py (they run the pipeline, not only the checks stage)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import gitq
from support.aging import age
from support.engine_case import EngineTest
from support.world import no_repo

from tltestkit import procsim
from tltestkit.plans import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE
from tltestkit.shellkit import sh

# isort: split
import contextlib
import os
import shlex
import time
from pathlib import Path
from unittest import mock

from support.briefs import brief_digest, linked_text
from support.fakes import as_bead, must_bead
from support.spawn import port_git, real_spawner
from support.who import who

from taskloop.adapters.check_probe import PathProbe
from taskloop.app.run import (
    engine,
    entry,
)
from tlgate import evidence as check_evidence
from tlgate.domain import lint
from tlgate.domain.writer_split import WriterSplit
from tlkernel import answers, childenv, plancheck
from tlkernel import checkmatchers as check_matchers
from tlkernel.config import EngineConfig
from tlkernel.env import snapshot
from tlkernel.ids import BeadId, CheckId
from tlkernel.plancheck import Adhoc, adhoc
from tlkernel.reviewmatchers import Tools
from tlkernel.waitenums import WaitWhat
from tlslots import config as wslots_config
from tltestkit.cfgs import cfg_with
from tltestkit.checks import ck, res, typed
from tltestkit.narrow import must
from tlwork.write.matchers import count_tests


class EngineChecksTest(EngineTest):
    def test_repo_checks_on_an_equal_tree_and_base_are_reused(self):
        count = Path(self.tmp.name) / "count"
        bump = procsim.fake("bump", procsim.appends(count))
        eng = self.checks_engine(checks=[{"id": "bump", "cmd": bump, "group": "tests"}])
        st = {"checks": [], "files": []}
        first = eng.run_checks(st, "s")
        again = eng.run_checks(st, "s")
        assert count.read_text() == "1"
        assert again[0].cached
        (self.wt / "new.txt").write_text("x\n")  # an untracked file changes the tree
        eng.run_checks(st, "s")
        assert count.read_text() == "11"
        assert first[0].exit == 0
    def test_checks_run_in_groups_fastest_first_and_stop_at_a_red_group(self):
        eng = self.checks_engine(checks=[{"id": "unit", "cmd": "true", "group": "tests"},
                                         {"id": "lint", "cmd": FALSE, "group": "static"}])
        res = eng.run_checks({"checks": ck(["true"]), "files": []}, "s")
        assert [(c.group, c.status) for c in res] == [("static", "failed"), ("tests", "skipped"), ("acceptance", "skipped")]
        assert "static failed" in res[1].why
    def test_a_repo_check_runs_only_when_its_paths_changed(self):
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": "true", "group": "tests", "when": ["client/**"]}])
        gitq.git("checkout", "-q", "-b", "task/t-1", cwd=eng.wt)
        assert eng.run_checks({"checks": [], "files": []}, "s")[0].status == "skipped"
        (self.wt / "client").mkdir()
        (self.wt / "client" / "a.cs").write_text("x\n")
        assert eng.run_checks({"checks": [], "files": []}, "s")[0].status == "passed"
    def test_a_flaky_check_gets_its_retries(self):
        mark = Path(self.tmp.name) / "seen"

        def red_first(cwd, env):
            first = not mark.exists()
            mark.write_text("")
            return (1 if first else 0), ""
        flaky = procsim.fake("flaky", red_first)
        eng = self.checks_engine(checks=[{"id": "flaky", "cmd": flaky, "group": "tests", "retry": 1}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        assert (res[0].exit, res[0].status, res[0].tries) == (0, "passed", 2)
    def sleeping_check(self, secs, counter):
        """A check that counts its runs in `counter` and would take `secs` seconds (the sim stops it at the wall limit, nothing sleeps)."""
        return procsim.fake(f"sleep-{secs}", procsim.takes(secs, then=procsim.appends(counter)))
    def test_a_timed_out_check_is_never_retried(self):
        n = Path(self.tmp.name) / "runs-timeout"
        eng = self.checks_engine(checks=[{"id": "hang", "cmd": self.sleeping_check(30, n), "group": "tests", "retry": 1}],
                                 check_wall_min=0.02)
        with mock.patch.object(eng, "warn") as warn:
            res = eng.run_checks({"checks": [], "files": []}, "s")
        assert (res[0].exit, res[0].tries, n.read_text()) == (124, 1, "1")
        assert "no retry: timed out after" in warn.call_args[0][0]
    def test_exit_124_from_the_command_itself_is_not_retried_either(self):
        n = Path(self.tmp.name) / "runs-124"
        cmd = procsim.fake("exits-124", procsim.appends(n, code=124, out="timeout: the command ran too long"))
        eng = self.checks_engine(checks=[{"id": "t", "cmd": cmd, "group": "tests", "retry": 2}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        assert (res[0].tries, n.read_text()) == (1, "1")
    def test_a_checks_own_wall_min_overrides_the_global_one(self):
        n = Path(self.tmp.name) / "runs-own"
        slow = self.sleeping_check(1.2, n)
        eng = self.checks_engine(checks=[{"id": "short", "cmd": slow, "group": "tests", "wall_min": 0.01}],
                                 check_wall_min=5)
        assert eng.run_checks({"checks": [], "files": []}, "s")[0].exit == 124
        eng2 = self.checks_engine(checks=[{"id": "long", "cmd": slow, "group": "tests", "wall_min": 0.1}],
                                  check_wall_min=0.01)
        assert eng2.run_checks({"checks": [], "files": []}, "s")[0].exit == 0
    @no_repo
    def test_a_passing_check_still_shows_its_notable_lines(self):
        out = check_evidence.compact([res("just check", 0, tail="lane light: ok\nunity steps run: client changed\nfoo\nbar\n439 passed")])
        assert "unity steps run" in out
        assert "439 passed" in out
    def test_a_repo_check_marked_cache_false_always_reruns(self):
        count = Path(self.tmp.name) / "count"
        bump = procsim.fake("bump", procsim.appends(count))
        eng = self.checks_engine(checks=[{"id": "bump", "cmd": bump, "group": "tests", "cache": False}])
        eng.run_checks({"checks": [], "files": []}, "s")
        eng.run_checks({"checks": [], "files": []}, "s")
        assert count.read_text() == "11"
    def test_a_check_that_is_not_an_argv_list_is_refused_with_the_allowed_form(self):
        wire = plancheck.to_wire(PLAN)
        bad = dict(wire, stages=[dict(wire["stages"][0], checks=["test -f f.txt && echo ok"])])
        errs = answers.check("plan", False, bad)
        assert len(errs) == 1
        assert "stages[0].checks[0]: Expected `object`" in errs[0]
        assert '["just", "name"]' in errs[0]
        assert answers.check("plan", False, plancheck.to_wire(PLAN)) == []
    def test_a_unity_play_mode_test_counts(self):  # lifesim-d5f.59: a [UnityTest] read as tests_added=0
        diff = ("+++ b/client/Assets/Tests/PlayMode/LiveSpeedBarTests.cs\n+        [UnityTest]\n"
                "+        public IEnumerator SpeedButtonsChooseAndLightTheHostSpeed()\n")
        assert count_tests(diff, EngineConfig().test_pattern) == (1, 0)
    @no_repo
    def test_tracker_checks_are_told_apart_from_code_that_mentions_bd(self):
        assert lint.tracker_checks(typed(dict(PLAN, risks=[{"what": "x", "check": "env X=1 bd show t-1"}]))) == ["env X=1 bd show t-1"]
        for ok in (HAS_F, "grep -rn 'bd list' src", "pytest tests/test_bd.py", "test -f abd"):
            assert lint.tracker_checks(typed(dict(PLAN, risks=[{"what": "x", "check": ok}]))) == [], ok
    def test_a_sleeping_check_is_cut_at_check_wall_min_not_node_timeout_min(self):
        eng = self.checks_engine(check_wall_min=0.01, node_timeout_min=45)
        res = eng.run_checks({"checks": ck([procsim.fake("sleep-30", procsim.takes(30))]), "files": []}, "s")
        assert (res[0].exit, res[0].status) == (124, "failed")
        assert "timed out after 0.01 min" in res[0].tail
    @no_repo
    def test_a_check_is_engine_only_by_its_last_duration_else_by_its_name(self):
        def only(cmd, secs):
            return WriterSplit(cfg_with(writer_check_max_s=60), secs).engine_only(cmd)
        assert only("just lint", {"just lint": 61})
        assert not only("just unity-tests", {"just unity-tests": 60})
        assert only("just play-tests", {})
        assert only("just test-all", {})
        assert not only("just display", {})
    @no_repo
    def test_a_tool_counts_only_backticked_or_after_a_run_verb(self):
        assert Tools.named("`UseCellBeside` handles a rotated slot; `justfile` has the recipe") == []
        assert Tools.named("nobody ran `shellcheck -x hooks/*.sh` or linted with ruff") == ["shellcheck", "ruff"]
        assert Tools.named("the biome transition fades in; no black screen between lots") == []
        assert Tools.named("`mypy` was not run; nobody checked with eslint") == ["mypy", "eslint"]
    def test_dry_check_reads_the_argv_not_a_shell_string(self):
        def plan(*checks, files=("new.txt",)):
            return typed(dict(PLAN, stages=[dict(PLAN["stages"][0], checks=list(checks), files=list(files))]))
        wt = PathProbe(self.wt, childenv.current_env(snapshot()))
        assert lint.dry_check(plan("test -f a.txt", "test -f new.txt", "grep -q '<(' a.txt", HAS_F), wt) == []
        assert lint.dry_check(plan("test -f $HOME/x", "cat dir/*.txt"), wt) == []  # no shell: a plain word, not judged as a path
        assert lint.dry_check(plan("python3 -m pytest -q tests", "python3 -c pass"), wt) == []
        assert lint.dry_check(plan("python3 tests/nope.py"), wt)
        assert lint.dry_check(plan("test -f missing.txt"), wt)[0].count("missing.txt")
        assert "is not an executable here" in lint.dry_check(plan("After building the player: python3 x.py"), wt)[0]
        for operator in ("&&", "||", "|", ";", ">", "2>&1"):
            assert "literal argument in an argv" in lint.dry_check(plan(shlex.join(["echo", "a", operator, "b"])), wt)[0], operator
        assert "string command again" in lint.dry_check(plan(shlex.join(["bash", "-c", "true"])), wt)[0]
        assert "string command again" in lint.dry_check(plan(shlex.join(["/bin/sh", "-lc", "true"])), wt)[0]
        if os.name != "nt":  # lint.dry_check compares os.path.normpath'd stage files with the check's "src/new.txt"
            assert lint.dry_check(plan("test -f src/new.txt", files=("src/",)), wt) == []
    @no_repo
    def test_linked_beads_are_at_most_ten_and_never_change_the_checkpoint_hash(self):
        names = " ".join(f"t-{k}" for k in range(20, 40))
        bead = dict(BEAD, description=names)
        def show(b, cwd=None):
            return {"id": b, "title": "T" + b, "status": "closed", "close_reason": "r"}
        out = linked_text("t-1", must_bead(bead), [], lambda b: as_bead(show(b)), lambda b: [])
        assert out.count("\n- t-") == 10
        a = brief_digest(must_bead(bead), [], owner_only=True)
        assert "Linked beads" not in a

    def test_checks_run_without_the_launchers_claude_session(self):
        c = wslots_config.load_cfg(str(self.wt), port_git())
        eng = engine.Engine(BeadId("t-1"), str(self.wt), c, store=self.store, env=snapshot(), spawner=real_spawner(),
            git=port_git(), who=who())
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "cli"}):
            session_env = procsim.fake("session-env", lambda cwd, env: (1 if env.get("CLAUDE_CODE_ENTRYPOINT") else 0, ""))
            res = eng.run_checks({"checks": ck([session_env]), "files": []}, "s")
        assert res[0].exit == 0

    def test_a_configured_checks_log_and_exit_reach_the_checks_after_it(self):
        cmd, n = self.counting_check("Passed: 12", ok_after=1)
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests"}])
        def reads(cwd, env):
            ok = "Passed: 12" in Path(env["TL_CHECK_LOG_UNITY_TESTS"]).read_text() and env["TL_CHECK_RC_UNITY_TESTS"] == "0"
            return (0 if ok else 1), ""
        read = procsim.fake("reads-the-log TL_CHECK_LOG_UNITY_TESTS TL_CHECK_RC_UNITY_TESTS", reads)
        res = eng.run_checks({"checks": ck([adhoc(read, (CheckId("unity-tests"),))]), "files": []}, "s")
        assert [c.exit for c in res] == [0, 0]  # the plan check ran after the repo check and read its log
        assert n.read_text() == "1"

    def test_the_same_command_under_distinct_registry_ids_runs_each_requirement(self):
        cmd, n = self.counting_check("ok", ok_after=1)
        eng = self.checks_engine(checks=[{"id": "a", "cmd": cmd, "group": "static", "wall_min": 1, "cache": False},
                                         {"id": "b", "cmd": cmd, "group": "tests", "wall_min": 2, "cache": False}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        assert (n.read_text(), [bool(c.reused) for c in res]) == ("2", [False, False])

    def test_a_slot_wait_in_a_check_is_read_and_capped_at_its_wall_time(self):
        cmd, _n = self.counting_check("unity-slot: x got slot 0 after 99999999s", ok_after=1)
        eng = self.checks_engine(checks=[{"id": "u", "cmd": cmd, "group": "tests"}])
        eng.run_checks({"checks": [], "files": []}, "s")
        assert 0 < eng.waited < 60
        eng.waits.add(99999999, WaitWhat.SLOT)
        assert eng.waited <= time.time() - eng.t0

    def test_budget_min_by_label_raises_the_budget_for_a_labelled_bead(self):
        eng = self.checks_engine(budget_min=5, budget_min_by_label={"unity": 300})
        age(eng, 8 * 60)
        with pytest.raises(engine.Blocked):
            eng.waits.budget_check()
        labelled = self.checks_engine(attrs={"labels": ["unity"]}, budget_min=5, budget_min_by_label={"unity": 300})
        age(labelled, 8 * 60)
        labelled.waits.budget_check()

    def test_a_compile_error_amid_library_or_asset_import_lines_is_retried_once(self):
        for ctx in ("Refreshing asset database", "Library/Bee/x.dll locked", "Temp/y missing"):
            assert check_matchers.failure_kind(ctx + "\nA.cs(1,1): error CS1002: ; expected") == "import", ctx
        cmd, _n = self.counting_check("Library/x\nA.cs(1,1): error CS1002: ; expected")
        eng = self.checks_engine(checks=[{"id": "imp", "cmd": cmd, "group": "tests", "retry": 0}])
        assert eng.run_checks({"checks": [], "files": []}, "s")[0].tries == 2

    def test_a_locked_editor_is_waited_for_with_backoff_then_passes(self):
        cmd, n = self.counting_check(self.LOCK[0], ok_after=3)
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "retry": 1}])
        with mock.patch.object(eng.checker, "sleep") as sleep:
            res = eng.run_checks({"checks": [], "files": []}, "s")
        assert (res[0].exit, res[0].status, n.read_text()) == (0, "passed", "3")
        assert [c[0][0] for c in sleep.call_args_list if c[0][0] >= 15] == [15, 30]  # other threads may sleep too

    def test_a_lock_is_waited_for_even_on_a_check_with_no_retry(self):
        cmd, n = self.counting_check(self.LOCK[0], ok_after=2)
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": cmd, "group": "tests", "retry": 0}])
        with mock.patch.object(eng.checker, "sleep"):
            res = eng.run_checks({"checks": [], "files": []}, "s")
        assert (res[0].exit, n.read_text()) == (0, "2")

    def test_a_stage_check_always_reruns_it_can_read_state_outside_the_tree(self):
        state = Path(self.tmp.name) / "editor-open"  # a running editor, a log, a bead comment: git cannot see them
        eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        gone = procsim.fake(f"editor-closed {state}", lambda cwd, env: (1 if state.exists() else 0, ""))
        st = {"checks": ck([gone]), "files": []}
        assert eng.run_checks(st, "s")[0].exit == 0
        state.write_text("x")
        again = eng.run_checks(st, "s")
        assert again[0].exit == 1
        assert not again[0].cached

    def test_a_failed_check_is_never_reused(self):
        count = Path(self.tmp.name) / "count"
        fails = procsim.fake("fails", procsim.appends(count, code=1))
        eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        st = {"checks": ck([fails]), "files": []}
        eng.run_checks(st, "s")
        again = eng.run_checks(st, "s")
        assert count.read_text() == "11"
        assert not again[0].cached

    def test_checks_run_without_a_shell(self):
        eng = engine.Engine(
            BeadId("t-1"),
            str(self.wt),
            wslots_config.load_cfg(str(self.wt), port_git()),
            store=self.store,
            env=snapshot(),
            spawner=real_spawner(),
            git=port_git(), who=who())
        res = eng.run_checks({"checks": [Adhoc(argv=("echo", "$HOME", "&&", "x;", "(y)"), reads=())], "files": []}, "s")
        assert res[0].exit == 0, res[0].tail
        assert "$HOME && x; (y)" in res[0].tail  # no expansion, no operator: every word reached the program as written

    def test_a_write_prompt_names_each_check_command_once_in_its_may_run_lists(self):
        # tl-7y6.6.12: the stage's checks and the where() text both listed "You may run these"
        cmd = procsim.fake("print-1", procsim.exits(0, "1"))
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[cmd, HAS_F])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]},
                                raw={"checks": [{"id": "x", "cmd": procsim.fake("print-2", procsim.exits(0, "2")), "group": "static"},
                                                {"id": "y", "cmd": "echo only-repo"}]})
        assert rc == 0, self.blocked
        w = next(p for (c, p) in zip(s.calls, s.prompts, strict=False) if c[0] == "worker")
        may = w[w.index("The stage's checks"):w.index("A check that mentions")]
        assert may.count(cmd) == 1
        assert may.count(HAS_F) == 1
        assert may.count("only-repo") == 1

    def test_fresh_drops_the_checkpoint(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, fresh=True)
        assert rc == 0
        assert s.calls[0][0] == "planner"
        assert "already accepted" not in s.prompts[0]

    def test_a_tree_changed_since_the_checkpoint_starts_over(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        sh("git", "checkout", "-q", "task/t-1", cwd=self.wt)  # a parked slot is left detached at the base
        (self.wt / "f.txt").write_text("someone edited it\n")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        assert s.calls[0][0] == "planner"
        assert "changed since" in self.eng.log_path.read_text()

    def test_a_slow_check_is_the_engines_and_a_fast_failed_check_is_the_writers_to_rerun(self):
        slow = "true unity-tests"
        fast = procsim.fake("red-on-d2 fast-one", lambda cwd, env: (1 if procsim.f_txt(cwd) == "d2" else 0, ""))
        rc, s = self.run_engine({"plan": [self.plan_with(slow, fast)], "write": [WRITE, WRITE], "review": [CLEAN]})
        assert rc == 0, self.blocked
        first, again = s.prompts[1], s.prompts[2]
        assert "The engine runs these, do not run them:\n- " + slow in first
        assert "You may run these:\n- " + fast in first
        assert (
            "never start a command you expect to take over a minute; never poll a running command more than 3 times"
            in first.replace("Never", "never")
        )
        you_may = again[again.index("Only the failed checks"):]
        assert "You may run these:\n- " + fast in you_may
        assert "- " + slow not in you_may.split("You may run these:")[1].split("If a command")[0]
        assert "do not run them:\n- " + slow not in again

    def test_a_brief_the_owner_changed_or_a_checkpoint_without_writer_seen_gets_the_full_prompt(self):
        _rc, _s = self.two_writes(ctx_k=40)
        args = (1, "g", "f.txt", "", "checks", "where", "fb", "")
        assert "The brief is unchanged" in must(self.eng.hand.delta(*args))
        (self.eng.run_dir / "brief.md").write_text("the owner answered: use X\n")  # an answer came in
        assert self.eng.hand.delta(*args) is None
        (self.eng.run_dir / "brief.md").write_text(self.eng.brief_file.read_text())
        self.eng.writer.seen = []  # a checkpoint of before this existed
        assert self.eng.hand.delta(*args) is None

    def test_run_task_refuses_the_main_checkout(self):
        a = mock.Mock(id="t-1", branch=None, pr=None, worktree=str(self.wt), slot=None, dry_run=True, fresh=False, quiet=True,
                      outcome_file=None)
        with mock.patch.object(entry, "Engine") as made, contextlib.chdir(self.wt):
            rc = entry.main(a, self.store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who())
        assert rc == 1
        made.assert_not_called()
