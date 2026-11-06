"""Whole beads through the Engine, moved out of tests/checks/test_check_rules.py (they run the pipeline, not only the checks stage)."""
import json
import sys
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.cfgs import cfg_with
from support.checks import ck, typed
from support.engine_case import EngineTest
from support.narrow import must
from support.plans import CLEAN, FALSE, PLAN, WRITE

from taskloop.app.checks import evidence
from taskloop.contracts import wire
from taskloop.contracts.checks import CheckRun
from taskloop.contracts.ids import CheckId
from taskloop.contracts.plancheck import adhoc
from taskloop.domain.checks import lint, planref

ST = {"checks": [], "files": []}



class OneCheckRun(EngineTest):

    def test_the_round_file_and_the_log_row_are_one_check_run(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        stored = must(self.eng.stores.check_run(self.eng.run_dir.name, 1).get())
        rows = [json.loads(x) for x in self.eng.log_path.read_text().splitlines() if '"kind": "checks"' in x]
        assert wire.load(CheckRun, dict(rows[0]["run"], v=CheckRun.V)) == stored
        assert stored.results and all(c.log for c in stored.results)

class ProducerDidNotRun(EngineTest):
    REPO: ClassVar[list[dict[str, Any]]] = [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests", "when": ["nothing/**"]}]
    READER = adhoc('test -r "$TL_CHECK_LOG_UNITY_TESTS"', (CheckId("unity-tests"),))
    def test_a_consumer_of_a_skipped_producer_is_skipped_never_failed(self):
        eng = self.checks_engine(checks=self.REPO)
        run = eng.run_checks({"checks": ck([self.READER]), "files": []}, "s")
        assert [c.status for c in run] == ["skipped", "skipped"]
        assert run.results[1].producer == "unity-tests"
        assert run.failed == []
        assert "(producer unity-tests did not run)" in "\n".join(evidence.round_lines(run.results))
    def test_a_consumer_of_a_check_the_round_does_not_have_is_skipped_too(self):
        eng = self.checks_engine(checks=[])
        run = eng.run_checks({"checks": ck([adhoc('test -r "$TL_CHECK_LOG_NOPE"', (CheckId("nope"),))]), "files": []}, "s")
        assert [(c.status, c.producer) for c in run] == [("skipped", "nope")]
    def test_a_genuinely_red_producer_fails_the_round_naming_it(self):
        eng = self.checks_engine(checks=[{"id": "unity-tests", "cmd": FALSE, "group": "tests"}])
        run = eng.run_checks({"checks": ck([self.READER]), "files": []}, "s")
        assert [c.id for c in run.failed] == ["unity-tests"]
        assert run.results[1].status == "skipped"
        assert run.results[1].producer == "unity-tests"
    def test_a_read_of_a_check_the_repo_does_not_have_is_refused_at_parse(self):
        cfg = cfg_with(checks=self.REPO)
        got = planref.refusals([adhoc("cat x", (CheckId("absent"),)), adhoc("cat x", (CheckId("unity-tests"),))], cfg)
        assert len(got) == 1
        assert "reads `absent`" in got[0]
        assert "unity-tests" in got[0]
    def test_the_plan_lint_rejects_a_read_of_the_evidence_folder_nothing_makes(self):
        def own(files, cmd):
            return typed(dict(PLAN, stages=[dict(PLAN["stages"][0], files=files, checks=[cmd])]))

        ev = ".task/t-1/evidence"
        assert len(lint.evidence_problems(own(["f.txt"], f"grep -q ok {ev}/out.log"), ev)) == 1
        assert lint.evidence_problems(own([ev + "/out.log"], f"grep -q ok {ev}/out.log"), ev) == []

    def test_it_costs_no_write_round(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.READER.to_dict()])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE] * 3, "review": [CLEAN]}, checks=self.REPO)
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls].count("worker") == 1
