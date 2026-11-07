"""Engine tests: the checks round."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import gitq, procsim
from support.check_host import CheckHostCase
from support.plans import BEAD, FALSE, HAS_F, PLAN
from support.world import no_repo

# isort: split
import os
import shlex
from pathlib import Path
from unittest import mock

from support.briefs import brief_digest, linked_text
from support.cfgs import cfg_with
from support.fakes import as_bead, must_bead

from taskloop.adapters import childenv
from taskloop.adapters.check_probe import PathProbe
from taskloop.app.checks import evidence as check_evidence
from taskloop.domain.checks import lint
from taskloop.domain.checks.writer_split import WriterSplit
from taskloop.domain.write.matchers import count_tests
from tlkernel import answers, plancheck
from tlkernel.config import EngineConfig
from tlkernel.env import snapshot
from tlkernel.reviewmatchers import Tools
from tltestkit.checks import ck, res, typed


class EngineChecksTest(CheckHostCase):
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
