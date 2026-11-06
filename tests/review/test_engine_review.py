"""Engine tests: review, verify and the follow-ups."""
import sys
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import time
import types
from contextlib import contextmanager
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.engine_case import EXIT_127, EngineTest, sh, stop, without_shims
from support.plans import BEAD, CLEAN, FALSE, PLAN, STILL_OPEN, WRITE, finding, review, verdict

# isort: split
from support.cfgs import cfg_with
from support.narrow import must
from support.spawn import port_git

from taskloop.app.land.checkout import Checkout
from taskloop.app.review.settles import Settles
from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots


class EngineReviewTest(EngineTest):
    def test_review_sends_an_unmet_requirement_back_to_the_same_writer(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["cant-sit-still still carries example: true"]), CLEAN]})
        assert rc == 0
        assert [c[1] for c in s.calls if c[0] == "worker"] == [None, "ref-write"]
        assert "cant-sit-still still carries example: true" in [p for (c, p) in zip(s.calls, s.prompts, strict=False)
                                                                     if c[0] == "worker"][1]

    def test_red_checks_never_reach_review_and_end_the_round(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE] * 4}, max_rounds=2, max_check_tries=2, max_replans=0, max_same_red=0)
        assert rc == 2
        assert "reviewer" not in [c[0] for c in s.calls]
        assert [c[0] for c in s.calls].count("worker") == 4
        assert "stuck" in self.blocked[0]
        assert (self.eng.stats["writes"], self.eng.stats["rounds"]) == (4, 2)

    def test_low_findings_are_noted_and_do_not_send_back(self):
        rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review(findings=[finding("low")])]})
        assert rc == 0
        assert any(c[:2] == ("comments", "add") and "a low fix" in c[3] for c in self.bd_calls)

    def test_a_medium_finding_sends_back(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE],
                                 "review": [review(findings=[finding("high")]), CLEAN]})
        assert rc == 0
        assert [c[0] for c in s.calls].count("worker") == 2

    def test_only_the_last_stages_review_checks_every_bead_requirement(self):
        two = dict(PLAN, stages=[PLAN["stages"][0], dict(PLAN["stages"][0], goal="add f again")])
        rc, s = self.run_engine({"plan": [two], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        assert rc == 0
        reviews = [p for (c, p) in zip(s.calls, s.prompts, strict=False) if c[0] == "reviewer"]
        assert "every requirement" not in reviews[0]
        assert "every requirement" in reviews[1]

    def test_a_review_question_an_accepted_requirement_decides_is_a_fix_round_citing_it(self):
        # lifesim-d5f.58: 'undo, or change R10?' became an owner decision ask; R10 already decides it
        q = "The writer changed the general rule; it contradicts R10. (a) undo and fix the test another way, (b) change R10"
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE],
                                 "review": [review(question=q, decided=self.R10), CLEAN]})
        assert rc == 0, self.blocked
        assert self.blocked == []
        assert self.ask() is None
        writes = [p for (c, p) in zip(s.calls, s.prompts, strict=False) if c[0] == "worker"]
        assert len(writes) == 2
        assert self.R10 in writes[1]
        assert "decided" in s.prompts[2]

    def test_a_stop_mid_stage_2_resumes_stage_2_at_its_round_with_the_same_thread(self):
        with self.stop_at("reviewer", 3):  # stage 1 accepted; stage 2 sent back once; stopped in its second review
            rc, _ = self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE, WRITE],
                                     "review": [CLEAN, review(unmet=["more"])]})
        assert rc == 2
        ck = self.checkpoint()
        assert (ck["stage"], ck["rounds"], ck["accepted"]) == (1, 1, [0])
        assert ck["writer"] == "ref-write"
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        assert rc == 0
        assert [c[0] for c in s.calls] == ["worker", "reviewer"]  # no plan, no stage 1
        assert s.calls[0][1] == "ref-write"                      # the writer's thread goes on
        assert "stage two" in s.prompts[0]
        assert "round 2" in self.eng.log_path.read_text()
        self.assertNoCheckpoint()                                # landed: nothing left to resume

    def test_the_writer_may_add_a_case_it_is_run_and_shown_to_the_review(self):
        seen, extra = self.counter("extra")
        w = dict(WRITE, new_cases=[{"criterion": "f.txt exists", "check": extra, "why": "found an edge"}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [w], "review": [CLEAN]})
        assert rc == 0
        assert seen.read_text() == "1"
        rv = s.prompts[2]
        assert "added by the writer" in rv
        assert "found an edge" in rv
        assert must(self.eng.plan_data)["cases"][-1]["by"] == "writer"

    def test_a_verify_ask_is_a_decision_and_takes_the_bead_out_of_the_pick_queue(self):
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        with self.store.stub(show=dict(BEAD, labels=["auto", "visual"])):
            _rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [STILL_OPEN]},
                                    pick_label="auto")
        assert (self.ask()["kind"], self.ask()["class"]) == ("decision", "external_fact")
        assert ("label", "remove", "t-1", "auto") in self.bd_calls

    def test_a_writer_or_reviewer_decision_carries_its_options_too(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Which?", options=self.CHOICES[:2])]})
        assert rc == 2
        assert [o["text"] for o in self.ask()["options"]] == ["B: keep it parked", "A: build the slice now"]
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, question="Which?", options=self.CHOICES[:2])]})
        assert rc == 2
        assert len(self.ask()["options"]) == 2

    def test_a_verify_ask_offers_right_and_a_wrong_that_opens_the_box(self):
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [STILL_OPEN]})
        assert (
            [(o["label"], o["action"], o["edit"]) for o in self.ask()["options"]]
            == [("Right, land it", "confirm", False), ("Wrong: say what", "text", True)]
        )

    def test_what_the_writer_could_not_check_goes_to_the_review_which_decides(self):
        # lifesim-jjso: the writer could not run Unity, the engine's cases then did; the land must not stop on that
        w = dict(WRITE, unchecked=[{"what": "the Unity tests need the host", "kind": "case"}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [w], "review": [CLEAN]})
        assert rc == 0, self.blocked
        assert "the Unity tests need the host" in s.prompts[2]

    def test_only_non_final_stages_are_told_a_later_stage_case_is_not_unchecked(self):
        rc, s = self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        assert rc == 0, self.blocked
        assert ["is not unchecked" in p for p in s.prompts[1:5]] == [True, True, False, False]

    RUFF: ClassVar[Any] = {"what": "nobody ran ruff on tools/*.py", "kind": "tooling"}

    def no_ruff(self, name):
        return None if name == "ruff" else "/usr/bin/" + name

    def unused(self, what, cfg, on_path=lambda name: None):
        return Settles(types.SimpleNamespace(wt=str(self.wt), cfg=cfg, on_path=on_path), port_git()).unused_tool(what)

    @contextmanager
    def ruff_cannot_start(self):
        # Tool discovery is mocked separately; a host install or mise shim must not decide this test's exit code.
        real_sh = engine.Engine.sh

        def run(eng, cmd, *args, **kwargs):
            if cmd == ["ruff", "check", "--no-fix", "."]:
                return 127, "ruff: command not found"
            return real_sh(eng, cmd, *args, **kwargs)

        with mock.patch.object(engine.Engine, "sh", autospec=True, side_effect=run) as run_:
            yield
        run_.assert_any_call(self.eng, ["ruff", "check", "--no-fix", "."], timeout=600)

    def test_an_unchecked_item_for_a_tool_the_repo_does_not_use_is_dropped_with_the_evidence(self):
        with mock.patch.object(engine, "tool_on_path", side_effect=self.no_ruff):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, unchecked=[self.RUFF])]})
        assert rc == 0, self.blocked
        assert self.ask() is None
        assert "reviewer" not in [c[0] for c in s.calls][3:]  # no verifier call for it
        verify = next(c[3] for c in self.bd_calls if c[:2] == ("comments", "add") and c[3].startswith("Verify (engine)"))
        assert "not a check here" in verify
        assert "which ruff: not found" in verify
        assert "git grep -w -I ruff" in verify
        causes = [json.loads(ln) for ln in self.eng.log_path.read_text().splitlines() if '"transition"' in ln]
        assert any(t["cause"] == "not_a_check" for t in causes)

    @EXIT_127
    @without_shims
    def test_an_unchecked_item_for_a_tool_the_repo_configures_still_goes_to_the_verifier(self):
        (self.wt / "justfile").write_text("lint:\n    ruff check tools\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "justfile", cwd=self.wt)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)
        with mock.patch.object(engine, "tool_on_path", side_effect=self.no_ruff), self.ruff_cannot_start():
            rc, _s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, unchecked=[self.RUFF])],
                                     "verify": [STILL_OPEN]})
        assert rc == 2
        assert (self.ask()["kind"], self.ask()["class"]) == ("decision", "external_fact")
        assert "ruff" in self.card()

    @EXIT_127
    @without_shims
    def test_an_unchecked_item_for_a_tool_on_the_path_still_goes_to_the_verifier(self):
        with mock.patch.object(engine, "tool_on_path", return_value="/opt/bin/ruff"), self.ruff_cannot_start():
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [dict(CLEAN, unchecked=[self.RUFF])],
                                     "verify": [STILL_OPEN]})
        assert rc == 2
        assert "ruff" in self.card()

    def test_prose_that_happens_to_name_a_tool_still_goes_to_the_verifier(self):
        cfg = wslots.load_cfg(str(self.wt), port_git())
        with mock.patch.object(engine, "tool_on_path", return_value=None):
            for what in ("the biome transition fades in", "no black screen between lots"):
                assert self.unused(what, cfg) == "", what

    def test_a_tool_the_tree_mentions_anywhere_still_goes_to_the_verifier(self):
        cfg = self.wt / ".config"
        cfg.mkdir()
        (cfg / "dotnet-tools.json").write_text(json.dumps({"tools": {"csharpier": {"version": "0.30.0"}}}))
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "tools", cwd=self.wt)
        with mock.patch.object(engine, "tool_on_path", return_value=None):
            assert self.unused("nobody ran csharpier on src/", wslots.load_cfg(str(self.wt), port_git())) == ""

    def test_only_the_unused_tool_item_is_dropped_the_rest_go_to_the_verifier(self):
        cfg = wslots.load_cfg(str(self.wt), port_git())
        with mock.patch.object(engine, "tool_on_path", side_effect=self.no_ruff):
            assert "not a check here" in self.unused(self.RUFF["what"], cfg, self.no_ruff)
            assert self.unused(self.GAPS[1]["what"], cfg, self.no_ruff) == ""

    def test_only_the_items_the_verifier_leaves_open_go_to_the_owner(self):
        answer = {"items": [verdict(1, "settled", "guid: 3f2a is unique"), verdict(2, "settled", "Boot.cs:14"),
                            verdict(3, "open", why="taste: it needs a phone and the owner's eye")]}
        rc, _ = self.verified(answer)
        assert rc == 2
        a = self.ask()
        assert a["kind"] == "decision"
        assert "the menu reads well on a phone" in self.card()
        assert "the owner's eye" in a["why"]
        assert "Boot() calls" not in a["why"]
        assert ".meta" not in self.card()

    def test_the_verifier_runs_once_and_what_its_fix_leaves_unchecked_goes_to_the_owner(self):
        answer = {"items": [verdict(1, "wrong", why="the guid is not unique"), verdict(2, "settled", "Boot.cs:14"),
                            verdict(3, "open", why="taste")]}
        left = dict(CLEAN, unchecked=[{"what": "the new guid is unique across Assets", "kind": "tooling"}])
        rc, s = self.verified(answer, write=[WRITE, WRITE], review=[dict(CLEAN, unchecked=self.GAPS), left])
        assert rc == 2
        assert [c[0] for c in s.calls].count("reviewer") == 3  # stage review, the verifier, the fix's review
        q = self.card()
        assert "the menu reads well on a phone" in q
        assert "the new guid is unique across Assets" in q

    def test_a_verifier_that_cannot_run_leaves_every_item_to_the_owner(self):
        out = stop("rate_limited", at=time.time() + 7200, say="no lane")
        rc, _ = self.verified(out, verify=[out])  # the lane is out for hours: given up at once
        assert rc == 2
        q = self.card()
        for item in self.GAPS:
            assert item["what"] in q
        assert "could not self-verify" in self.eng.log_path.read_text()

    def test_links_that_do_not_open_go_back_to_the_writer_and_unverified_ones_to_the_owner(self):
        """tl-bxk.7 (lifesim-ggi: 7 of 19 links 403 from the host, 'verified' from a sandbox with no network)."""
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        eng, opened = self.eng, []

        def fake(url):
            opened.append(url)
            return (url.startswith("https://docs."), "HTTP 403")
        eng.link_fn = fake
        with mock.patch.object(Checkout, "task_diff", return_value=self.RESEARCH_DIFF):
            review = {"findings": []}
            eng.link_check.link_judged(review)
            assert len(review["findings"]) == 1
            assert "https://fab.com/s/abc did not open from the engine's host (HTTP 403)" in review["findings"][0]["fix"]
            assert review["findings"][0]["file"] == "notes/hair.md"
            assert [(u["kind"], u["source"]) for u in eng.unverified] == [("external_fact", "https://sketchfab.com/m/x")]
            assert "Beards: (unverified)" in eng.unverified[0]["what"]
            opened.clear()
            review = {"findings": []}
            eng.link_check.link_judged(review)  # the link that opened is not opened again; the two that did not are
            assert sorted(opened) == ["https://fab.com/s/abc", "https://sketchfab.com/m/x"]
            assert len(eng.unverified) == 1
        eng.cfg = cfg_with(eng.cfg, check_links=False)
        review = {"findings": []}
        eng.link_check.link_judged(review)
        assert review["findings"] == []

    def test_a_host_that_reaches_nothing_makes_no_findings_and_a_raising_check_is_a_failed_link(self):
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        eng = self.eng
        eng.link_fn = lambda url: (False, "no such host")
        with mock.patch.object(Checkout, "task_diff", return_value=self.RESEARCH_DIFF):
            review = {"findings": []}
            eng.link_check.link_judged(review)
            assert (review["findings"], eng.unverified) == ([], [])  # offline: nothing the writer can fix
            assert "looks offline" in eng.log_path.read_text()
            eng.link_tries.clear()
            eng.link_fn = lambda url: (_ for _ in ()).throw(RuntimeError("boom"))
            review = {"findings": []}
            eng.link_check.link_judged(review)
            assert len(review["findings"]) == 2  # a check that raised failed that link; the run goes on

    def test_an_infrastructure_failure_in_verify_fails_the_run_instead_of_being_swallowed(self):
        # lifesim 2026-10-22: the 53 beads failed in the verify step, whose Blocked used to mean "the owner checks them"
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r], "verify": [self.bad_request()]})
        assert (rc, self.ask(), self.blocked) == (2, None, [])
        assert self.eng.result().why.startswith("failed: infrastructure: bad_request")
