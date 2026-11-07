"""E4 (tl-4qh): what a round of checks decides, with real processes and git: a producer that did not run, a red the base also has,
the same red three rounds in a row, a retry that cannot change the answer, the compile errors Unity wrote elsewhere, the plan lint."""
from typing import Any, ClassVar

from support.check_host import CheckHostCase

from tlgate import evidence
from tlgate.domain import lint, planref
from tlkernel.ids import CheckId
from tlkernel.plancheck import adhoc
from tltestkit.cfgs import cfg_with
from tltestkit.checks import ck, typed
from tltestkit.plans import FALSE, PLAN

ST = {"checks": [], "files": []}


class Base(CheckHostCase):
    pass


class ProducerDidNotRun(Base):
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
