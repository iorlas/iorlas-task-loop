"""E4 (tl-4qh): what a round of checks decides, with real processes and git: a producer that did not run, a red the base also has,
the same red three rounds in a row, a retry that cannot change the answer, the compile errors Unity wrote elsewhere, the plan lint."""
import json
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support.builders import cfg_with
from support.checks import ck, typed
from support.engine_case import CLEAN, PLAN, WRITE

from taskloop.app.checks import evidence
from taskloop.contracts import wire
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.ids import CheckId
from taskloop.contracts.plancheck import adhoc
from taskloop.domain.checks import lint, planref

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
        stored = self.eng.stores.check_run(self.eng.run_dir.name, 1).get()
        rows = [json.loads(x) for x in self.eng.log_path.read_text().splitlines() if '"kind": "checks"' in x]
        self.assertEqual(wire.load(CheckRun, dict(rows[0]["run"], v=CheckRun.V)), stored)
        self.assertTrue(stored.results and all(c.log for c in stored.results))


class ProducerDidNotRun(Base):
    REPO: ClassVar[list[dict[str, Any]]] = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests", "when": ["nothing/**"]}]
    READER = adhoc('test -r "$TL_CHECK_LOG_UNITY_TESTS"', (CheckId("unity-tests"),))

    def test_a_consumer_of_a_skipped_producer_is_skipped_never_failed(self):
        eng = self.checks_engine(checks=self.REPO)
        run = eng.run_checks({"checks": ck([self.READER]), "files": []}, "s")
        self.assertEqual([c.status for c in run], ["skipped", "skipped"])
        self.assertEqual(run.results[1].producer, "unity-tests")
        self.assertEqual(run.failed, [])
        self.assertIn("(producer unity-tests did not run)", "\n".join(evidence.round_lines(run.results)))

    def test_a_consumer_of_a_check_the_round_does_not_have_is_skipped_too(self):
        eng = self.checks_engine(checks=[])
        run = eng.run_checks({"checks": ck([adhoc('test -r "$TL_CHECK_LOG_NOPE"', (CheckId("nope"),))]), "files": []}, "s")
        self.assertEqual([(c.status, c.producer) for c in run], [("skipped", "nope")])

    def test_it_costs_no_write_round(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.READER.to_dict()])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE] * 3, "review": [CLEAN]}, checks=self.REPO)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)

    def test_a_genuinely_red_producer_fails_the_round_naming_it(self):
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": te.FALSE, "group": "tests"}])
        run = eng.run_checks({"checks": ck([self.READER]), "files": []}, "s")
        self.assertEqual([c.id for c in run.failed], ["unity-tests"])
        self.assertEqual(run.results[1].status, "skipped")
        self.assertEqual(run.results[1].producer, "unity-tests")

    def test_a_read_of_a_check_the_repo_does_not_have_is_refused_at_parse(self):
        cfg = cfg_with(checks=self.REPO)
        got = planref.refusals([adhoc("cat x", (CheckId("absent"),)), adhoc("cat x", (CheckId("unity-tests"),))], cfg)
        self.assertEqual(len(got), 1)
        self.assertIn("reads `absent`", got[0])
        self.assertIn("unity-tests", got[0])

    def test_the_plan_lint_rejects_a_read_of_the_evidence_folder_nothing_makes(self):
        def own(files, cmd):
            return typed(dict(PLAN, stages=[dict(PLAN["stages"][0], files=files, checks=[cmd])]))

        ev = ".task/t-1/evidence"
        self.assertEqual(len(lint.evidence_problems(own(["f.txt"], f"grep -q ok {ev}/out.log"), ev)), 1)
        self.assertEqual(lint.evidence_problems(own([ev + "/out.log"], f"grep -q ok {ev}/out.log"), ev), [])


if __name__ == "__main__":
    unittest.main()
