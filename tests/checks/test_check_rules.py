"""E4 (tl-4qh): what a round of checks decides, with real processes and git: a producer that did not run, a red the base also has,
the same red three rounds in a row, a retry that cannot change the answer, the compile errors Unity wrote elsewhere, the plan lint."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support import engine_case as te  # noqa: E402
from support.engine_case import CLEAN, PLAN, PY, WRITE, engine, review  # noqa: E402
from support.builders import cfg_with  # noqa: E402
from taskloop.app.checks import evidence  # noqa: E402
from taskloop.app.checks.attempts import Attempts  # noqa: E402
from taskloop.contracts.checks import Check, CheckRun  # noqa: E402
from taskloop.contracts.codec import from_json  # noqa: E402
from taskloop.domain.checks import lint, retry  # noqa: E402

ST = {"checks": [], "files": []}


class Base(unittest.TestCase):
    """The engine harness of tests/test_engine.py, borrowed method by method (its setUp builds the repo, the fake bd and the config)."""

    wt: Path
    tmp: Any
    eng: Any
    blocked: list[str]

    def setUp(self):
        te.EngineTest.setUp(cast(Any, self))

    def tearDown(self):
        te.EngineTest.tearDown(cast(Any, self))

    def fake_bd(self, *a, **kw):
        return te.EngineTest.fake_bd(cast(Any, self), *a, **kw)

    def run_engine(self, answers, **cfg):
        return te.EngineTest.run_engine(cast(Any, self), answers, **cfg)

    def checks_engine(self, **cfg):
        return te.EngineTest.checks_engine(cast(Any, self), **cfg)

    def counting_check(self, line, ok_after=None):
        return te.EngineTest.counting_check(cast(Any, self), line, ok_after)


class OneCheckRun(Base):
    def test_the_round_file_and_the_log_row_are_one_check_run(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        stored = self.eng.stores.check_run(self.eng.run_dir.name, 1).read()
        rows = [json.loads(x) for x in self.eng.log_path.read_text().splitlines() if '"kind": "checks"' in x]
        self.assertEqual(from_json(CheckRun, dict(rows[0]["run"], v=CheckRun.V)), stored)
        self.assertTrue(stored.results and all(c.log for c in stored.results))


class ProducerDidNotRun(Base):
    REPO = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests", "when": ["nothing/**"]}]
    READER = 'test -r "$TL_CHECK_LOG_UNITY_TESTS"'

    def test_a_consumer_of_a_skipped_producer_is_skipped_never_failed(self):
        eng = self.checks_engine(checks=self.REPO)
        run = eng.run_checks({"checks": [self.READER], "files": []}, "s")
        self.assertEqual([c.status for c in run], ["skipped", "skipped"])
        self.assertEqual(run.results[1].producer, "unity-tests")
        self.assertEqual(run.failed, [])
        self.assertIn("(producer unity-tests did not run)", "\n".join(evidence.round_lines(run.results)))

    def test_a_consumer_of_a_check_the_repo_does_not_have_is_skipped_too(self):
        eng = self.checks_engine(checks=[])
        run = eng.run_checks({"checks": ['test -r "$TL_CHECK_LOG_NOPE"'], "files": []}, "s")
        self.assertEqual([(c.status, c.producer) for c in run], [("skipped", "NOPE")])

    def test_it_costs_no_write_round(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.READER])])
        with mock.patch.object(lint, "producer_problems", return_value=[]):  # past the plan lint: the engine alone decides
            rc, s = self.run_engine({"plan": [plan], "write": [WRITE] * 3, "review": [CLEAN]}, checks=self.REPO)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)

    def test_a_genuinely_red_producer_fails_the_round_naming_it(self):
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": te.FALSE, "group": "tests"}])
        run = eng.run_checks({"checks": [self.READER], "files": []}, "s")
        self.assertEqual([c.id for c in run.failed], ["unity-tests"])
        self.assertEqual(run.results[1].status, "skipped")
        self.assertEqual(run.results[1].producer, "unity-tests")

    def test_the_plan_lint_rejects_a_read_nothing_produces(self):
        cfg = cfg_with(checks=[{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests", "when": ["client/**"]}])
        own = lambda files, cmd: dict(PLAN, stages=[dict(PLAN["stages"][0], files=files, checks=[cmd])])
        reader = 'grep -q ok "$TL_CHECK_LOG_UNITY_TESTS"'
        self.assertEqual(len(lint.producer_problems(own(["f.txt"], reader), cfg)), 1)
        self.assertEqual(lint.producer_problems(own(["client/a.cs"], reader), cfg), [])
        self.assertEqual(len(lint.producer_problems(own(["f.txt"], 'cat "$TL_CHECK_LOG_ABSENT"'), cfg)), 1)
        ev = ".task/t-1/evidence"
        self.assertEqual(len(lint.evidence_problems(own(["f.txt"], "grep -q ok %s/out.log" % ev), ev)), 1)
        self.assertEqual(lint.evidence_problems(own([ev + "/out.log"], "grep -q ok %s/out.log" % ev), ev), [])


class SameRed(Base):
    def test_three_identical_reds_in_a_row_stop_and_park_with_one_ask_naming_the_signature(self):
        cmd, _ = self.counting_check("boom: the same line")
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[cmd])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE] * 6, "review": [CLEAN]}, max_check_tries=6, max_rounds=6)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 3)
        a = te.read_ask()
        self.assertEqual((a["class"], a["status"]), ("no_progress", "open"))
        card = te.card_of(a)
        self.assertIn("boom: the same line", card)
        self.assertIn("3 fix rounds", card)

    def test_reds_that_differ_do_not_stop_the_run(self):
        n = Path(self.tmp.name) / "k"
        code = ("import os,sys; k=(int(open(%r).read()) if os.path.exists(%r) else 0)+1; open(%r,'w').write(str(k)); "
                "print('red number', k); sys.exit(1)" % (str(n), str(n), str(n)))
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[PY + " -c " + te.shq(code)])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE] * 4}, max_check_tries=4, max_rounds=4, max_replans=0)
        self.assertGreaterEqual([c[0] for c in s.calls].count("worker"), 4)  # none of them stopped for a repeated red
        self.assertFalse([b for b in self.blocked if "same" in b])


class Retries(Base):
    def host(self):
        calls = []
        h = SimpleNamespace(killed=False, wall_hit=False, wt=Path(self.tmp.name), warned=[], calls=calls,
                            warn=lambda t: h.warned.append(t), waits=SimpleNamespace(note_slot_waits=lambda *a: None),
                            sh=lambda cmd, **kw: (calls.append(cmd), (1, "AssertionError: 1 != 2"))[1])
        return h

    def test_a_check_slower_than_20_minutes_is_not_run_again_on_the_output_it_failed_with(self):
        h = self.host()
        c = Check(id="slow", cmd="just slow", retry=3)
        sig = "AssertionError: 1 != 2"
        clock = iter(range(0, 100000, int(retry.SLOW_S) + 60))  # every reading of the clock is 21 minutes on
        with mock.patch("taskloop.app.checks.attempts.time.time", side_effect=lambda: next(clock)):
            out = Attempts(cast(Any, h), cast(Any, None), {"slow": (sig, 1300.0)}, lambda s: None).run(c, Path(self.tmp.name) / "l.log", {})
        self.assertEqual((out.tries, len(h.calls)), (1, 1))
        self.assertTrue(any("not run again" in w for w in h.warned))

    def test_the_same_slow_check_failing_with_other_output_still_gets_its_retry(self):
        self.assertFalse(retry.skip_slow_rerun("a", "b", retry.SLOW_S + 1))
        self.assertTrue(retry.skip_slow_rerun("a", "a", retry.SLOW_S + 1))
        self.assertFalse(retry.skip_slow_rerun("a", "a", 60))


class BaseRed(Base):
    def test_a_check_red_on_the_untouched_base_too_is_not_the_writers_and_not_counted(self):
        cmd, n = self.counting_check("boom: red since before")
        eng = self.checks_engine(checks=[{"id": "old", "cmd": cmd, "group": "tests"}], base_red=True)
        run = eng.run_checks(ST, "s")
        self.assertEqual(([c.base_red for c in run], run.failed, n.read_text()), ([True], [], "2"))  # the tree, then the base
        self.assertIn("red on the untouched base too", "\n".join(evidence.round_lines(run.results)))
        eng.run_checks(ST, "s")
        self.assertEqual(n.read_text(), "3")  # the base answer is remembered by its sha: only the tree ran again

    def test_a_red_the_task_made_is_the_writers(self):
        mark = "wip-%d.txt" % id(self)
        eng = self.checks_engine(checks=[{"id": "clean", "cmd": "test ! -e " + mark, "group": "tests"}], base_red=True)
        (self.wt / mark).write_text("x\n")  # in the tree, not in the base
        run = eng.run_checks(ST, "s")
        self.assertEqual(([c.base_red for c in run], [c.id for c in run.failed]), ([False], ["clean"]))

    def test_checks_red_since_the_base_cost_the_writer_no_round(self):
        cmd, _ = self.counting_check("boom: red since before")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE] * 4, "review": [CLEAN]}, base_red=True,
                                checks=[{"id": "old", "cmd": cmd, "group": "tests"}])
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)

    def test_base_red_is_one_switch(self):
        cmd, n = self.counting_check("boom")
        eng = self.checks_engine(checks=[{"id": "old", "cmd": cmd, "group": "tests"}], base_red=False)
        run = eng.run_checks(ST, "s")
        self.assertEqual(([c.base_red for c in run], n.read_text()), ([False], "1"))


class WriterAndProjectLog(Base):
    def test_a_check_says_writer_true_and_the_prompt_lists_it_for_the_writer(self):
        slow = PY + ' -c "pass"'
        eng = self.checks_engine(checks=[{"id": "an", "cmd": slow, "group": "static", "writer": True},
                                         {"id": "full", "cmd": "just full", "group": "tests", "writer": False}], writer_check_max_s=1)
        text = eng.briefing.stage_checks_text([slow, "just full"])
        self.assertIn("You may run these:\n- " + slow, text)
        self.assertIn("The engine runs these, do not run them:\n- just full", text)

    def test_the_first_20_cs_errors_of_the_project_files_log_reach_the_writer(self):
        (self.wt / "client" / "Logs").mkdir(parents=True)
        (self.wt / "client" / "Logs" / "unity-project-files.log").write_text(
            "Compiling\n" + "".join("A%d.cs(1,1): error CS%04d: broken %d\n" % (i, 1000 + i, i) for i in range(30)))
        cmd = PY + ' -c "import sys; print(\'project files could not be regenerated\'); sys.exit(1)"'
        eng = self.checks_engine(checks=[{"id": "unity-analyzers", "cmd": cmd, "group": "static"}])
        res = eng.run_checks(ST, "s").results[0]
        self.assertEqual(res.tail.count("error CS"), 20)
        self.assertIn("broken 0", res.tail)
        self.assertNotIn("broken 20", res.tail)
        self.assertIn("error CS1019", (Path(eng.run_dir) / res.log).read_text())

    def test_a_red_with_its_own_compile_errors_is_left_alone(self):
        (self.wt / "client" / "Logs").mkdir(parents=True)
        (self.wt / "client" / "Logs" / "unity-project-files.log").write_text("B.cs(1,1): error CS0001: other\n")
        cmd = PY + ' -c "import sys; print(\'A.cs(1,1): error CS1002: ; expected\'); sys.exit(1)"'
        eng = self.checks_engine(checks=[{"id": "unity-analyzers", "cmd": cmd, "group": "static"}])
        self.assertNotIn("other", eng.run_checks(ST, "s").results[0].tail)


class ReplanKeepsCounters(Base):
    def test_a_replan_does_not_start_the_review_count_again(self):
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE], "review": [review(unmet=["x"]), review(unmet=["x"])]},
                                max_rounds=1, max_replans=1, max_total_reviews=1)
        self.assertEqual(rc, 2)
        self.assertEqual(self.eng.stats["reviews"], 2)
        self.assertIn("2 reviews ran in this run", te.card_of(te.read_ask()))

    def test_the_minutes_a_run_spent_before_a_replan_stay_on_its_budget(self):
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE], "review": [review(unmet=["x"]), CLEAN]},
                                max_rounds=1, max_replans=1)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(self.eng.stats["replans"], 1)
        self.assertEqual(self.eng.stats["reviews"], 2)


if __name__ == "__main__":
    unittest.main()
