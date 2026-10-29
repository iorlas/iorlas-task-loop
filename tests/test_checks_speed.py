"""Check rounds that cost less: per-check input cache, cheap-first order, duplicate runs, wall limits."""
import json
import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import procsim
from support.builders import cfg_with
from support.engine_case import PY, engine, pyc, real_git  # noqa: F401
from support.waits import until

from taskloop.adapters import (
    check_files,
)
from taskloop.app.checks.cache import InputKeys
from taskloop.app.wire import doctor
from taskloop.contracts.argv import text_of
from taskloop.contracts.checks import Check, Durations
from taskloop.domain.checks import durations, inputs, lint
from taskloop.domain.checks.names import norm
from taskloop.domain.checks.order import CheckOrder


def ignored_paths(wt, globs, exclude=()):
    listed = check_files.ignored_files(str(wt), inputs.pathspec(globs, exclude), os.environ)
    return inputs.matching(listed, globs, exclude)


class SpeedTest(te.EngineTest):
    wt: Path
    tmp: Any


    def bump(self, name="count"):
        n = Path(self.tmp.name) / name
        return procsim.fake(f"bump {name}", procsim.appends(n)), n

    def sh_counter(self, code=0):
        """The unity-tests command: counts its runs in a file, prints 'Passed: 12', exits `code`."""
        n = Path(self.tmp.name) / "unity-runs"
        return procsim.fake(f"unity-run {code}", procsim.appends(n, code=int(code), out="Passed: 12")), n

    def notes(self, eng):
        return [json.loads(ln).get("text", "") for ln in eng.log_path.read_text().splitlines() if '"kind": "note"' in ln]


class InputCache(SpeedTest):
    ST: ClassVar[Any] = {"checks": [], "files": []}

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
        self.assertTrue(again[0].cached)
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
        other = procsim.fake(cmd + " other", procsim.appends(n))
        eng3 = self.checks_engine(checks=[{"id": "unity", "cmd": other, "group": "tests", "inputs": ["client/**"]}])
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
            t_ = {p[:-3] for p in tracked if inputs.inputs_hash({p: tracked[p]}, [g.replace("X", "cs")])}
            i_ = {p[:-4] for p in ignored_paths(str(self.wt), [g.replace("X", "gen")])}
            self.assertEqual(t_, i_, g)
        self.assertEqual(
            {p[:-4] for p in ignored_paths(str(self.wt), ["client/*/*.gen"])}, {"client/App/a", "client/Core/c", "client/Other/d"}
        )
        self.assertEqual(
            {p[:-4] for p in ignored_paths(str(self.wt), ["client/{App,Core}/**"])}, {"client/App/a", "client/App/sub/b", "client/Core/c"}
        )

    def test_the_ignored_walk_is_cut_to_the_globs_folders_and_the_excluded_ones(self):
        seen = []
        real = check_files.subprocess.run
        with mock.patch.object(check_files.subprocess, "run", side_effect=lambda args, **kw: (seen.append(args), real(args, **kw))[1]):
            ignored_paths(str(self.wt), ["client/Assets/{App,Core}/**"], ["client/Assets/App/*/Gen/**"])
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
        c = Check(id="x", cmd="x", inputs=["client/**"], inputs_only=True, exclude=["client/Gen/**"])

        def key():
            return InputKeys(self.wt, self.tree(), "b", os.environ).key(c)
        k = key()
        (self.wt / "client" / "Gen" / "i.gen").write_text("2\n")  # an excluded ignored file
        (self.wt / "client" / "Gen" / "t.cs").write_text("2\n")  # an excluded tracked (here: untracked-new) file
        self.assertEqual(key(), k)
        (self.wt / "client" / "a.cs").write_text("2\n")
        self.assertNotEqual(key(), k)
        self.assertNotEqual(InputKeys(self.wt, self.tree(), "b", os.environ).key(c.replace(exclude=[])), key())

    def tree(self):
        return self.eng_tree.checkout.tree_hash()

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
            self.assertFalse(again[0].cached)

    def test_doctor_reports_a_dead_inputs_glob(self):
        (self.wt / "a.cs").write_text("1\n")
        te.sh("git", "add", "-A", cwd=self.wt)
        te.sh("git", "commit", "-qm", "a", cwd=self.wt)
        (self.wt / ".task-loop.json").write_text(json.dumps({"engine": {"checks": [
            {"id": "u", "argv": ["x"], "inputs": ["*.cs"]}, {"id": "v", "argv": ["y"], "inputs": ["client/{A,B}/**"]}]}}))
        te.sh("git", "add", ".task-loop.json", cwd=self.wt)
        te.sh("git", "commit", "-qm", "doctor config", cwd=self.wt)
        te.sh("git", "update-ref", "refs/remotes/origin/main", "HEAD", cwd=self.wt)
        warns = doctor.git_warnings(str(self.wt))
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
        self.assertFalse(eng.run_checks(self.ST, "s")[0].cached)

    def test_inputs_hash_ignores_files_outside_the_globs(self):
        a = {"x/a": "100644 blob 1", "y/b": "100644 blob 2"}
        b = dict(a, **{"y/b": "100644 blob 3"})
        self.assertEqual(inputs.inputs_hash(a, ["x/**"]), inputs.inputs_hash(b, ["x/**"]))
        self.assertNotEqual(inputs.inputs_hash(a, ["y/**"]), inputs.inputs_hash(b, ["y/**"]))
        self.assertEqual(inputs.inputs_hash(a, ["z/**"]), "")


class CheapFirst(SpeedTest):
    def slow_then_fast(self):
        mark = Path(self.tmp.name) / "order"
        def step(name):
            return procsim.fake(f"step-{name}", procsim.appends(mark, f"{name} "))
        return mark, step("slow"), step("quick")

    def seed(self, eng, cmd, secs):
        doc = eng.stores.durations.of(check_files.repo_key(str(self.wt), eng.checkout.git_env()))
        doc.write(durations.merged(doc.read() or Durations(), [(cmd, secs)] * 3))

    def test_the_cheaper_check_runs_first_and_a_red_stops_the_round(self):
        mark, slow, _ = self.slow_then_fast()
        quick_red = procsim.fake("quick-red", procsim.appends(mark, "quick ", code=1))
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": slow, "group": "tests"},
                                         {"id": "quick", "cmd": quick_red, "group": "tests"}])
        self.seed(eng, slow, 400)
        self.seed(eng, quick_red, 2)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([c.id for c in res], ["quick", "slow"])
        self.assertEqual([c.status for c in res], ["failed", "skipped"])
        self.assertEqual(mark.read_text(), "quick ")

    def test_cheap_checks_all_run_before_the_stop_and_only_green_runs_are_recorded(self):
        _mark, slow, quick = self.slow_then_fast()
        red = te.FALSE
        eng = self.checks_engine(checks=[{"id": "a", "cmd": red, "group": "tests"}, {"id": "b", "cmd": quick, "group": "tests"},
                                         {"id": "c", "cmd": slow, "group": "tests"}])
        self.seed(eng, slow, 400)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([(c.id, c.status) for c in res], [("a", "failed"), ("b", "passed"), ("c", "skipped")])
        hist = (eng.stores.durations.of(check_files.repo_key(str(self.wt), eng.checkout.git_env())).read() or Durations()).runs
        self.assertNotIn(norm(red), hist)
        self.assertIn(norm(quick), hist)

    def test_unknown_commands_count_as_cheap_and_durations_are_recorded(self):
        _mark, slow, quick = self.slow_then_fast()
        eng = self.checks_engine(checks=[{"id": "known", "cmd": slow, "group": "tests"},
                                         {"id": "new", "cmd": quick, "group": "tests"}])
        self.seed(eng, slow, 90)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([c.id for c in res], ["new", "known"])
        hist = (eng.stores.durations.of(check_files.repo_key(str(self.wt), eng.checkout.git_env())).read() or Durations()).runs
        self.assertEqual(len(hist[norm(quick)]), 1)
        self.assertEqual(len(hist[norm(slow)]), 4)

    def test_a_check_reading_another_checks_log_stays_after_it(self):
        reader = procsim.fake("reader TL_CHECK_LOG_SLOW", lambda cwd, env: (0 if env.get("TL_CHECK_LOG_SLOW") else 1, ""))
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": "true", "group": "tests"},
                                         {"id": "reader", "cmd": reader, "group": "tests"}])
        self.seed(eng, "true", 300)
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual([(c.id, c.status) for c in res], [("slow", "passed"), ("reader", "passed")])

    def test_order_ignores_sub_five_second_noise(self):
        items = [Check(id="a", cmd="a"), Check(id="b", cmd="b")]
        order = CheckOrder(Durations(runs={"a": [3.0], "b": [0.1]}))
        self.assertEqual(order.sort(items, {}), [0, 1])


class Duplicates(SpeedTest):
    def test_a_plan_check_that_is_the_repo_checks_argv_takes_its_result(self):
        cmd, n = self.sh_counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests"}])
        res = eng.run_checks({"checks": [cmd], "files": []}, "s")
        self.assertEqual(n.read_text(), "1")
        self.assertEqual(
            [(c.id == "unity-tests", c.status, bool(c.reused)) for c in res], [(True, "passed", False), (False, "passed", True)]
        )

    def test_another_argv_around_the_same_recipe_runs_as_written(self):
        cmd, n = self.sh_counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests", "cache": False}])
        res = eng.run_checks({"checks": ["env FOO=1 " + cmd], "files": []}, "s")
        self.assertEqual(
            (n.read_text(), [c.status for c in res]), ("11", ["passed", "passed"])
        )  # the repo check, then the wrapper's own run

    def test_a_red_recipe_ends_the_round_before_its_copy(self):
        red, n = self.sh_counter(1)
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": red, "group": "tests"}])
        res = eng.run_checks({"checks": [red], "files": []}, "s")
        self.assertEqual(([c.status for c in res], n.read_text()), (["failed", "skipped"], "1"))

    def test_equal_argv_lists_are_one_command_whatever_the_spelling(self):
        cmd, n = self.sh_counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests"}])
        res = eng.run_checks({"checks": [cmd.replace(" ", "   ")], "files": []}, "s")
        self.assertEqual((n.read_text(), [bool(c.reused) for c in res]), ("1", [False, True]))


class Schedule(SpeedTest):
    """tl-7y6.7.11 / .7 / .16 (R09): one launch per command, Unity last, the ban on Unity in acceptance."""
    # yxbb.3-20261025-005743 engine-checks.r1.json, from ~/.config/task-loop/runs (read-only): the repo checks of lifesim's
    # .task-loop.json (wall_min 30 on the two test checks) and the round's items with the seconds they took.
    REPO: ClassVar[Any] = [
        {"id": "fmt", "cmd": "just fmt-check-changed", "group": "static"},
        {"id": "text", "cmd": "just text", "group": "static"},
        {"id": "unity-analyzers", "cmd": "just unity-analyzers", "group": "static"},
        {"id": "unity-tests", "cmd": "just unity-tests", "group": "tests", "wall_min": 30},
        {"id": "unity-play-tests", "cmd": "just unity-play-tests", "group": "tests", "wall_min": 30},
    ]
    GREP = shlex.join(["python3", "tools/assert_log.py", "TL_CHECK_RC_UNITY_PLAY_TESTS", "TL_CHECK_LOG_UNITY_PLAY_TESTS",
                       "total=[1-9][0-9]* passed=[1-9][0-9]* failed=0 skipped=0"])
    R1: ClassVar[Any] = {
        "just fmt-check-changed": 2,
        "just text": 0,
        "just worker-plan": 0,
        "python3 tools/select_tests.py --phase coordinator": 0,
        "env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.tests.test_select_tests": 0,
        "dotnet csharpier check ./client/Assets/Tests/PlayMode/ShareableLoopTests.cs": 1,
        "just text theme-check client-layers": 1,
        "just unity-analyzers": 104,
        "just unity-tests": 190,
        "just unity-play-tests": 571,
        GREP: 0,
    }
    ACCEPTANCE_R1: ClassVar[Any] = ["just worker-plan", "python3 tools/select_tests.py --phase coordinator",
                     "env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.tests.test_select_tests",
                     "dotnet csharpier check ./client/Assets/Tests/PlayMode/ShareableLoopTests.cs", "just text theme-check client-layers",
                     "just unity-analyzers", "just unity-tests", "just unity-play-tests", GREP,
                     "just unity-play-tests", "just unity-play-tests", "just unity-play-tests"]

    def replay(self, repo, accept, secs, red=(), **cfg):
        """Run one check round with a fake shell: no process starts; each launch costs secs[cmd] simulated seconds.
        Returns (results, [launched commands], simulated seconds per result id)."""
        eng = self.checks_engine(checks=repo, **cfg)
        launched = []

        def fake(argv, timeout=3600, check=False, save=None, env=None, pin=False, what="command", **kw):
            if argv[0] == "git":
                return real(argv, timeout=timeout, check=check, save=save, env=env, pin=pin, what=what)
            cmd = text_of(argv)
            launched.append(cmd)
            eng.wall_hit = False
            if save:
                Path(save).write_text(f"ran {cmd}\n")
            return (1 if cmd in red else 0), "passed"
        real = eng.sh
        cast(Any, eng).sh = fake
        res = eng.run_checks({"checks": accept, "files": []}, "s")
        return res, launched, {i: secs.get(c.cmd, 0) if c.log else 0 for i, c in enumerate(res)}

    def test_a_plan_copy_with_a_longer_limit_than_the_repo_check_is_one_launch(self):
        cmd, n = self.sh_counter()
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": cmd, "group": "tests", "wall_min": 30, "cache": False}])
        res = eng.run_checks({"checks": [cmd], "files": []}, "s")  # the plan's copy gets check_wall_min, 60
        self.assertEqual(eng.cfg.check_wall_min, 60)
        self.assertEqual((n.read_text(), [bool(c.reused) for c in res]), ("1", [False, True]))

    def test_a_first_run_that_timed_out_under_a_shorter_limit_is_not_reused_by_a_longer_one(self):
        n = Path(self.tmp.name) / "slow-runs"
        slow = procsim.fake("slow-1.2", procsim.takes(1.2, then=procsim.appends(n)))
        eng = self.checks_engine(checks=[{"id": "short", "cmd": slow, "group": "tests", "wall_min": 0.01, "cache": False},
                                         {"id": "long", "cmd": slow, "group": "tests", "wall_min": 1, "cache": False}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual(([c.exit for c in res], n.read_text()), ([124, 0], "11"))

    def test_replay_yxbb3_r1_the_acceptance_copies_of_the_unity_checks_add_nothing(self):
        res, launched, _secs = self.replay(self.REPO, self.ACCEPTANCE_R1, self.R1)
        for c in ("just unity-analyzers", "just unity-tests", "just unity-play-tests"):
            self.assertEqual(launched.count(c), 1, c)  # r1 launched unity-tests and unity-play-tests twice
        copies = [r for r in res if r.group == "acceptance" and r.cmd.startswith("just unity-")]
        self.assertEqual(len(copies), 6)  # the analyzers, unity-tests and four play-test copies, as in r1
        self.assertTrue(all(r.reused for r in copies))
        # r1 as recorded spent 869 s on the repo checks plus 208 s (unity-tests) and 536 s (unity-play-tests) on acceptance copies
        self.assertEqual(sum(self.R1[c] for c in launched), 869)

    def test_acceptance_that_reads_no_check_log_is_judged_before_the_unity_group(self):
        repo = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"}, {"id": "fmt", "cmd": "just fmt", "group": "static"}]
        _res, launched, _ = self.replay(repo, ["just cheap-accept", "test -r TL_CHECK_LOG_UNITY_TESTS"], {})
        self.assertEqual(launched, ["just fmt", "just cheap-accept", "just unity-tests", "test -r TL_CHECK_LOG_UNITY_TESTS"])

    def test_a_red_acceptance_check_stops_the_round_before_unity_with_the_reason(self):
        repo = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests"},
                {"id": "unity-analyzers", "cmd": "just unity-analyzers", "group": "static"}]
        accept = ["just cheap-accept", "test -r TL_CHECK_LOG_UNITY_TESTS", "just unity-tests"]
        res, launched, _ = self.replay(repo, accept, {}, red={"just cheap-accept"})
        self.assertEqual(launched, ["just cheap-accept"])
        skipped = [(c.id, c.why) for c in res if c.status == "skipped"]
        self.assertEqual(len(skipped), 4)
        self.assertTrue(all("failed first" in w or "did not run" in w for _, w in skipped))
        self.assertIn("producer unity-tests did not run", dict(skipped)["test -r TL_CHECK_LOG_UNITY_TESTS"])

    def test_replay_of_acceptance_only_red_rounds_never_relaunches_unity(self):
        # a round shaped like yxbb.3 r1 whose only red is a cheap acceptance check, replayed three times (the rounds a writer fixes)
        for bad in ("just worker-plan", "just text theme-check client-layers", "python3 tools/select_tests.py --phase coordinator"):
            res, launched, _ = self.replay(self.REPO, self.ACCEPTANCE_R1, self.R1, red={bad})
            self.assertFalse([c for c in launched if "unity" in c], bad)
            self.assertEqual([c.id for c in res if c.status == "failed"], [bad])

    def test_the_plan_validator_rejects_unity_recipes_in_acceptance_and_a_limit_above_the_cap(self):
        cfg = cfg_with(checks=self.REPO)
        plan = dict(te.PLAN, stages=[dict(te.PLAN["stages"][0], checks=[
            "just unity-tests", "env CI=1 just unity-play-tests", "echo 'just unity-tests'", "just unity-foo", "just fmt"])])
        got = lint.unity_problems(plan, cfg)
        self.assertEqual(len(got), 3)
        self.assertIn("TL_CHECK_LOG_UNITY_TESTS", got[0])
        self.assertIn("TL_CHECK_LOG_UNITY_PLAY_TESTS", got[1])
        self.assertIn("do not launch it from acceptance", got[2])
        over = dict(te.PLAN, stages=[dict(te.PLAN["stages"][0], checks=["just play --timeout_ms 7200000"])])
        self.assertEqual(len(lint.own_timeout_problems(over, 60)), 1)
        self.assertEqual(lint.repo_check_of("just unity-tests", cfg), "unity-tests")
        self.assertIsNone(lint.repo_check_of("just unity-tests foo", cfg))


class WallLimit(SpeedTest):
    def alive(self, mark):
        return subprocess.run(["pgrep", "-f", "sleep " + mark], capture_output=True, text=True, check=False).stdout.strip()

    @te.POSIX_CHECK
    @te.real_proc("a wall-limit kill reaches a descendant that left the process group (setsid): only a real tree shows it")
    def test_a_timeout_keeps_the_output_and_kills_a_setsid_descendant(self):
        mark = f"72.{os.getpid()}"
        code = (f"import os,subprocess,sys,time\nprint('before', flush=True)\nsubprocess.Popen(['sleep','{mark}'], "
                f"start_new_session=True)\ntime.sleep(30)")
        eng = self.checks_engine(checks=[{"id": "t", "cmd": PY + " -c " + te.shq(code), "group": "tests", "wall_min": 0.01}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual(res[0].exit, 124)
        self.assertIn("before", (Path(eng.run_dir) / res[0].log).read_text())
        self.assertTrue(until(lambda: self.alive(mark) == "", limit=5), "the setsid descendant outlived the check")


if __name__ == "__main__":
    unittest.main()
