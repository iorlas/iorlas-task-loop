"""Engine tests: the land, the push, the rebase and the conflict fix."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import os
import threading
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import gitq, homes, procsim
from support.engine_case import POSIX_CHECK, EngineTest
from support.logs import records
from support.plans import CLEAN, HAS_F, PLAN, STILL_OPEN, WRITE, verdict
from support.waits import until

from taskloop.adapters import (
    landlock,
)
from tlkernel.locator import RunLocator
from tlkernel.paths import ConfigDir


class EngineLand2Test(EngineTest):
    def test_waiting_for_the_land_lock_ends_the_open_node_first_and_is_logged(self):
        if os.name == "nt":
            pytest.skip("POSIX flock")
        eng = self.checks_engine()
        path = landlock.land_lock_path(homes.cfg(), gitq.git("remote", "get-url", "origin", cwd=eng.wt) or str(eng.wt))
        eng.steps.begin("review", "review")
        got, go = [], threading.Event()

        def holder():
            with landlock.os_lock(path, "other-bead"):
                got.append(1)
                go.wait(60)
        t = threading.Thread(target=holder)
        t.start()
        assert until(lambda: got), "the holder never took the lock"
        # The holder lets go only once the engine has logged that it waits (a fixed delay raced a loaded machine: the holder could let
        # go before the engine asked, and no wait was ever recorded).
        threading.Thread(target=lambda: until(lambda: records(eng, "wait_start")) and go.set()).start()
        with eng.lander.lock():
            pass
        t.join()
        (start,), (w,) = records(eng, "wait_start"), records(eng, "wait_end")
        assert (
            (start["what"], start["holder"], start["id"] == w["id"], w["in_budget"])
            == ("land_lock", "other-bead", True, False)
        )  # tl-y35
        kinds = [r["kind"] for r in records(eng)]
        assert kinds.index("step_end") < kinds.index("wait_start")  # the open step ended before the wait began
        assert kinds.index("wait_end") < kinds.index("lock")
        assert kinds.index("lock") < kinds.index("unlock")
        assert w["wait_seconds"] >= 0

    def test_a_free_land_lock_logs_no_wait(self):
        eng = self.checks_engine()
        with eng.lander.lock():
            pass
        assert self.wait_records(eng) == []

    def test_an_unchecked_requirement_stops_the_land_with_a_verify_ask(self):
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [STILL_OPEN]})
        assert rc == 2
        a = self.ask()
        assert a["class"] == "external_fact"
        assert "the cited spec link did not open" in a["detail"]["text"]
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == ""

    def test_the_gate_named_as_unchecked_lands_without_an_ask(self):
        # lifesim-5ban.3: 'the full gate and diff coverage, reserved for the engine' stopped the land; the gate runs there
        gate = "true"
        r = dict(CLEAN, unchecked=[{"what": f"the full `{gate}` gate and diff coverage", "kind": "requirement"}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]}, gate=gate)
        assert rc == 0, self.blocked
        assert self.ask() is None
        assert f"runs the gate (`{gate}`) once, at land" in s.prompts[2]
        assert "never an unchecked item" in s.prompts[2]
        assert "write no case for it" in s.prompts[0]

    def test_a_repo_check_that_passed_this_round_named_as_unchecked_lands_without_an_ask(self):
        unit = procsim.fake("print-1", procsim.exits(0, "1"))
        r = dict(CLEAN, unchecked=[{"what": f"{unit} on the whole tree", "kind": "case"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]},
                                checks=[{"id": "unit", "cmd": unit, "group": "tests"}])
        assert rc == 0, self.blocked
        assert self.ask() is None

    @POSIX_CHECK
    def test_a_case_named_as_unchecked_once_the_last_stage_ran_every_case_lands_without_an_ask(self):
        # lifesim-gfr.31.1: 'there is no nographics.out in evidence yet' reached the owner after the case writing it passed
        plan = dict(
            PLAN,
            cases=[{"criterion": "f.txt exists", "check": procsim.fake("has-f case", procsim.has_f)}],
        )
        r = dict(CLEAN, unchecked=[{"what": "I could not run the case 'f.txt exists': there is no evidence.out yet",
                                    "kind": "case"}])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE], "review": [r]})
        assert rc == 0, self.blocked
        assert self.ask() is None
        assert "unchecked item dropped" in self.eng.log_path.read_text()
        assert "one at a time" in s.prompts[2]
        assert "a case is never an unchecked item" in s.prompts[2]
        assert '"kind": "adhoc"' in s.prompts[0]

    def test_a_case_item_with_no_case_in_the_plan_still_stops_the_land(self):
        r = dict(CLEAN, unchecked=[{"what": "the filter that selects nothing", "kind": "case"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [STILL_OPEN]})
        assert rc == 2
        assert (self.ask()["kind"], self.ask()["class"]) == ("decision", "external_fact")

    def test_a_stage_check_that_passed_named_as_unchecked_lands_without_an_ask(self):
        r = dict(CLEAN, unchecked=[{"what": f"`{HAS_F}` on the final tree", "kind": "requirement"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]})
        assert rc == 0, self.blocked
        assert self.ask() is None

    def test_an_answered_verify_ask_goes_straight_to_land(self):
        with self.store.stub(comments=self.verify_then_answer("confirm")):
            rc, s = self.run_engine({})
        assert rc == 0, self.blocked
        assert s.calls == []
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d2"

    def test_a_verify_answer_with_a_yes_and_evidence_goes_straight_to_land(self):
        text = "Right. The log shows the link opens and returns the spec."
        with self.store.stub(comments=self.verify_then_answer("confirm", text)):
            rc, s = self.run_engine({})
        assert rc == 0, self.blocked
        assert s.calls == []

    def test_a_verify_answer_the_planner_finds_needs_nothing_more_lands(self):
        with self.store.stub(comments=self.verify_then_answer("text", "Link is fine, checked.")):
            rc, s = self.run_engine({"plan": [dict(PLAN, stages=[], summary="nothing left")]})
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner"]
        assert gitq.git("show", "origin/main:f.txt", cwd=str(self.wt)) == "d2"
        assert self.eng.plan_summary == "nothing left"  # the pipeline stores the returned plan summary

    def test_a_verify_answer_on_the_dashboard_lands_it(self):
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [STILL_OPEN]})
        self.file_answer("confirm")
        with self.store.stub(comments=[]):
            rc, s = self.run_engine({})
        assert rc == 0, self.blocked
        assert s.calls == []

    def test_an_earlier_stage_unchecked_item_a_later_review_clears_lands_without_an_ask(self):
        # lifesim-gfr.31.1: stage 1 could not run the last stage's case; stage 2 ran it green, its review was clean,
        # and the land still stopped on the stale stage-1 item
        r1 = dict(CLEAN, unchecked=[{"what": "the -nographics run, the last stage's job", "kind": "case"}])
        rc, s = self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [r1, CLEAN]})
        assert rc == 0, self.blocked
        assert self.ask() is None
        assert "the -nographics run, the last stage's job" in s.prompts[4]  # re-judged by the later review

    def test_an_earlier_stage_unchecked_item_a_later_review_keeps_stops_the_land(self):
        item = {"what": "the cited spec link did not open", "kind": "link"}
        rc, _ = self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE],
                                 "review": [dict(CLEAN, unchecked=[item]), dict(CLEAN, unchecked=[item])],
                                 "verify": [STILL_OPEN]})
        assert rc == 2
        assert (self.ask()["kind"], self.ask()["class"]) == ("decision", "external_fact")
        assert self.ask()["detail"]["text"].count("the cited spec link did not open") == 1

    def test_an_unchecked_minor_item_lands_and_labels_the_bead_for_a_look(self):
        r = dict(CLEAN, unchecked=[{"what": "the tooltip wording on a phone", "kind": "other"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]})
        assert rc == 0
        assert ("label", "add", "t-1", "needs-owner-check") in [c[:4] for c in self.bd_calls]

    def test_unchecked_items_the_verifier_settles_land_without_an_ask(self):
        # lifesim-d5f.46, lifesim-fld.26.15: the supervisor settled each in a minute with read-only commands
        settled = {"items": [verdict(1, "settled", "rg -c 'guid: 3f2a' Assets → 1 match; fileFormatVersion: 2 as the siblings"),
                             verdict(2, "settled", "Boot.cs:14 `Wire();`"),
                             verdict(3, "settled", "evidence/menu.png shows the menu at 390px")]}
        rc, s = self.verified(settled)
        assert rc == 0, self.blocked
        assert self.ask() is None
        assert s.calls[3] == ("reviewer", None, "openai")  # read-only, another family than the writer
        brief = s.prompts[3]
        for item in self.GAPS:
            assert item["what"] in brief
        assert str(self.eng.evidence_dir) in brief
        assert "f.txt" in brief  # the diff summary
        assert "Add f" in brief  # the task
        for word in ("sandbox", "escalat", "git"):
            assert word not in brief.lower()
        said = [c[3] for c in self.bd_calls if c[:2] == ("comments", "add")]
        verify = next(c for c in said if c.startswith("Verify (engine)"))
        assert "Boot.cs:14 `Wire();`" in verify
        assert "settled" in verify
        reflect = next(c for c in said if c.startswith("Reflect (engine)"))
        assert "self-verified=3 settled, 0 wrong, 0 open" in reflect
        trace = json.loads((homes.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        assert [v["verdict"] for v in trace["verified"]] == ["settled"] * 3
        assert trace["verified"][1]["evidence"] == "Boot.cs:14 `Wire();`"
        assert trace["verified"][1]["what"] == "Boot() calls the new Wire()"

    def test_an_item_the_verifier_finds_wrong_goes_to_a_fix_round_then_lands(self):
        answer = {"items": [verdict(1, "wrong", why="the .meta guid 3f2a is also in Old.cs.meta: make it unique"),
                            verdict(2, "settled", "Boot.cs:14"), verdict(3, "settled", "evidence/menu.png")]}
        rc, s = self.verified(answer, write=[WRITE, WRITE], review=[dict(CLEAN, unchecked=self.GAPS), CLEAN])
        assert rc == 0, self.blocked
        assert [c[0] for c in s.calls] == ["planner", "worker", "reviewer", "reviewer", "worker", "reviewer"]
        assert "also in Old.cs.meta: make it unique" in s.prompts[4]
        assert self.eng.fixes == 1
        assert self.ask() is None
        verify = next(c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Verify (engine)"))
        assert "wrong" in verify

    def test_close_reason_says_what_landed_and_a_refused_close_is_a_warning(self):
        with self.store.stub(bd_fn=lambda *argv: mock.Mock(returncode=1 if argv[0] == "close" else 0, stdout="", stderr="refused")):
            _rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        assert "to main: do it" in self.closed[0]
        assert len(self.closed[0]) > 40
        log = RunLocator(ConfigDir(Path(os.environ["XDG_CONFIG_HOME"]) / "task-loop")).of_bead("t-1")[-1].log
        assert "bd refused to close" in log.read_text()

    def test_a_done_answer_whose_text_says_unknown_argument_lands_normally(self):
        said = "the CLI printed: error: unknown argument; schema note: \"code\":\"invalid_json_schema\""
        rc, _ = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, text=said, say=said)], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert self.closed and self.closed[0].startswith("merged ")
