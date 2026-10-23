"""tl-bxk.13: stage handoffs (docs/design/stages.md). Reuses test_engine's harness without re-running its tests."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_engine as te  # noqa: E402
from test_engine import BEAD, CLEAN, FALSE, HAS_F, PLAN, WRITE, engine, tl  # noqa: E402,F401


class StagesTest(unittest.TestCase):
    setUp = te.EngineTest.setUp
    tearDown = te.EngineTest.tearDown
    fake_bd = te.EngineTest.fake_bd
    commit_base_cfg = te.EngineTest.commit_base_cfg
    run_engine = te.EngineTest.run_engine

    def created(self):
        return [a[1] for a in self.bd_calls if a and a[0] == "create"]


class EmptyPlan(StagesTest):
    """13.2: the planner says the work is done and only follow-up beads are left."""

    def test_an_empty_plan_with_leftovers_files_them_and_closes_done(self):
        plan = dict(PLAN, stages=[], leftovers=[{"title": "File the table bead", "why": "the sheet lists a table"}])
        rc, s = self.run_engine({"plan": [plan]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        self.assertEqual(self.created(), ["File the table bead"])
        self.assertTrue(self.closed and self.closed[0].startswith("done with nothing to land"))
        self.assertEqual(self.blocked, [])

    def test_an_empty_plan_with_nothing_to_file_still_fails(self):
        rc, s = self.run_engine({"plan": [dict(PLAN, stages=[])]})
        self.assertNotEqual(rc, 0)
        self.assertTrue(self.blocked and "no stages" in self.blocked[0])

    def test_done_when_counts_as_acceptance_criteria(self):
        has = engine.has_criteria
        self.assertTrue(has({"description": "Goal.\n\n## Done when\n- x works\n"}))
        self.assertTrue(has({"description": "Goal.\n\nDone when: x works"}))
        self.assertTrue(has({"description": "Goal.\n\n**Done when**\n- x works"}))
        self.assertTrue(has({"description": "## Acceptance Criteria\n- x"}))
        self.assertFalse(has({"description": "Goal only."}))
        self.assertFalse(has({"description": "## Done when\n\n## Notes\nnothing"}))
        self.assertFalse(has({"description": ""}))


class BadChecks(StagesTest):
    """13.3: the writer names a broken check loosely; the engine still finds it."""

    LONG = FALSE + " ; echo padding-so-the-check-is-long-enough-to-shorten"

    def test_flagged_why_matches_loose_names(self):
        c = {"id": "x", "cmd": "grep -qE 'name=\"GameLogTests\"[^>]*result=\"Passed\"' client/Logs/unity-tests.xml"}
        why = engine.flagged_why
        self.assertEqual(why(c, [{"cmd": c["cmd"], "why": "a"}]), "a")
        self.assertEqual(why(c, [{"cmd": "grep   -qE 'name=\"GameLogTests\"[^>]*result=\"Passed\"'\nclient/Logs/unity-tests.xml", "why": "b"}]), "b")
        self.assertEqual(why(c, [{"cmd": "grep -qE 'name=\"GameLogTests\"...unity-tests.xml", "why": "c"}]), "c")
        self.assertEqual(why(c, [{"cmd": "`" + c["cmd"] + "`", "why": "d"}]), "d")
        self.assertEqual(why(dict(c, id="unity-tests"), [{"cmd": "unity-tests", "why": "e"}]), "e")
        self.assertEqual(why(c, [{"cmd": "grep -qE 'other'...nothing.xml", "why": "f"}]), "")
        self.assertEqual(why(c, [{"cmd": "grep", "why": "g"}]), "")  # too short to say which check
        self.assertEqual(why(c, []), "")

    def test_a_shortened_bad_check_replans_at_once(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.LONG])])
        cmd = plan["stages"][0]["checks"][0]
        flag = dict(WRITE, bad_checks=[{"cmd": cmd[:25] + "..." + cmd[-12:], "why": "cannot pass"}])
        rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "planner", "worker", "reviewer"])


class Deferred(StagesTest):
    """13.1: the reviewer is told what the plan set aside; 'file beads' is an engine step; an owner item with a bead lands."""

    LEFT = [{"title": "File the table and chair beads", "why": "the sheet lists them; the engine files them"}]

    def eng_(self):
        return engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))

    def test_the_review_prompt_lists_what_the_plan_set_aside(self):
        rc, s = self.run_engine({"plan": [dict(PLAN, leftovers=self.LEFT)], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        review = s.prompts[2]
        self.assertIn("Already set aside", review)
        self.assertIn("File the table and chair beads", review)
        self.assertIn("Never list one as unmet", review)

    def test_no_set_aside_section_without_leftovers(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertNotIn("Already set aside", s.prompts[2])

    def test_filing_beads_in_any_wording_is_an_engine_step_when_there_are_leftovers(self):
        e = self.eng_()
        for w in ("File beads for the table, chairs and sink", "Follow-up beads for each object are to be filed",
                  "The nine beads are not filed", "Create a bead per object", "file follow-up tasks"):
            self.assertFalse(e.engine_does(w), w + " (no leftovers yet)")
        e.leftovers = [{"title": "x", "why": "y"}]
        for w in ("File beads for the table, chairs and sink", "Follow-up beads for each object are to be filed",
                  "The nine beads are not filed", "Create a bead per object", "file follow-up tasks"):
            self.assertTrue(e.engine_does(w), w)
        self.assertFalse(e.engine_does("The beads cover all nine objects"))  # a claim about the result goes to the verifier

    def test_an_owner_item_with_an_owner_review_bead_in_the_leftovers_lands_unverified(self):
        e = self.eng_()
        e.leftovers = [{"title": "Owner review of the retuned knob values and placeholder art", "why": "iqad"}]
        item = {"what": "Owner sign-off on the retuned knob values and the placeholder art", "kind": "owner_decision"}
        self.assertTrue(e.backed_by_leftover(item["what"]))
        self.assertEqual(e.engine_steps([item]), [])
        self.assertEqual([u["what"] for u in e.unverified], [item["what"]])
        other = {"what": "Whether the storyteller preset is the intended default", "kind": "owner_decision"}
        self.assertEqual(e.engine_steps([other]), [other])
        e.leftovers = [{"title": "Tune the knob values and placeholder art", "why": "later"}]  # not an owner bead
        self.assertFalse(e.backed_by_leftover(item["what"]))


class Scope(StagesTest):
    """13.5: a checkable note outside the done-when is a follow-up, not a verify gap."""

    def test_an_item_outside_the_done_when_is_filed_not_verified(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        e.scope = "Acceptance Criteria\n- the soak passes with three lifers across five seeds"
        e.plan_data = dict(PLAN)
        inside = {"what": "the soak holds with three lifers on seed 4", "kind": "checkable"}
        outside = {"what": "Sit To Stand and Laying Sleeping poses were not probed", "kind": "checkable"}
        taste = {"what": "Sit To Stand and Laying Sleeping poses look right", "kind": "taste"}
        self.assertEqual(e.out_of_scope([inside, outside, taste]), [inside, taste])
        self.assertEqual(len(e.leftovers), 1)
        self.assertIn("Sit To Stand", e.leftovers[0]["title"])

    def test_with_no_acceptance_text_nothing_moves(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        item = {"what": "Sit To Stand was not probed", "kind": "checkable"}
        self.assertEqual(e.out_of_scope([item]), [item])
        self.assertEqual(e.leftovers, [])

    def test_acceptance_text_reads_the_field_and_the_description_from_the_heading(self):
        txt = engine.acceptance_text({"acceptance_criteria": "A works", "description": "Intro.\n## Done when\n- B works\n"})
        self.assertIn("A works", txt)
        self.assertIn("B works", txt)
        self.assertNotIn("Intro", txt)

    def test_a_note_outside_the_done_when_does_not_stop_the_run(self):
        with mock.patch.object(tl, "show", return_value=dict(BEAD, acceptance_criteria="f.txt exists and holds data")):
            review = dict(CLEAN, unchecked=[{"what": "the wallpaper colour was not probed", "kind": "checkable", "source": ""}])
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertTrue(any("wallpaper" in t for t in self.created()))


class Handoff(StagesTest):
    """13.6, 13.7: the rounds reach the planner of an amend; lows are not listed twice; a big writer starts the next stage fresh."""

    def test_the_amend_planner_sees_what_the_rounds_did(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        flag = dict(WRITE, summary="tried the rename", bad_checks=[{"cmd": FALSE, "why": "it exits 1 whatever the code does"}])
        rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        amend = s.prompts[2]
        self.assertIn("<rounds>", amend)
        self.assertIn("tried the rename", amend)
        self.assertIn("bad_checks", amend)
        handoff = json.loads((self.eng.run_dir / "handoff.json").read_text())
        self.assertEqual(handoff["rounds"][0]["kind"], "bad_checks")

    def test_a_low_finding_is_not_listed_again_by_the_next_review(self):
        first = dict(CLEAN, findings=[te.finding("medium"), dict(te.finding("low"), fix="rename the helper")])
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [first, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        reviews = [p for p, c in zip(s.prompts, s.calls) if c[0] == "reviewer"]
        self.assertNotIn("already noted", reviews[0])
        self.assertIn("already noted", reviews[1])
        self.assertIn("rename the helper", reviews[1])

    def test_the_rounds_text_keeps_the_newest_within_its_cap(self):
        e = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        for k in range(8):
            e.note_round("stage 1/1", k + 1, "review", "w" * 300, ["x" * 200])
        text = e.rounds_text()
        self.assertLessEqual(len(text), engine.HANDOFF_CAP + 700)
        self.assertIn("round 8", text)
        self.assertNotIn("round 1,", text)

    TWO = dict(PLAN, stages=[PLAN["stages"][0], dict(PLAN["stages"][0], goal="add g")])

    def boundary(self, ctx_k, **cfg):
        path = Path(self.tmp.name, "session.jsonl")
        n = int(ctx_k * 1000) - 100
        path.write_text(json.dumps({"type": "user"}) + "\n" + json.dumps({"type": "assistant", "message": {"usage": {
            "input_tokens": 3, "cache_read_input_tokens": n, "cache_creation_input_tokens": 97}}}) + "\n")
        extra = {"family": "claude", "transcript": str(path)}
        return self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]},
                               j_extra={"write": [extra, extra]}, **cfg)

    def test_a_writer_session_over_100k_starts_the_next_stage_fresh(self):
        rc, s = self.boundary(120)  # under the 150k a claude session may grow to inside a stage
        self.assertEqual(rc, 0, self.blocked)
        writes = [(p, c) for p, c in zip(s.prompts, s.calls) if c[0] == "worker"]
        self.assertIsNone(writes[1][1][1])
        self.assertIn("fresh session for the next one", writes[1][0])
        self.assertIn("add f", writes[1][0])  # the accepted stage's goal

    def test_a_smaller_session_goes_on_and_the_limit_is_the_repos_to_set(self):
        rc, s = self.boundary(90)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"][1], "ref-write")
        rc, s = self.boundary(120, write_fresh_stage_k=0)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"][1], "ref-write")


class RepeatedChecks(StagesTest):
    """13.4: a slow command wrapped in two checks, or around a repo check, goes back to the planner once."""

    def wrap(self, out):
        return "mkdir -p ev && just unity-tests > ev/%s.out 2>&1 && grep -q Passed ev/%s.out" % (out, out)

    def test_repeats_are_found_through_redirects_and_wrappers(self):
        e = engine.Engine("t-1", str(self.wt), dict(engine.load_cfg(str(self.wt)), checks=[
            {"id": "tests", "cmd": "just fast-tests", "group": "tests"}]))
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.wrap("a"), self.wrap("b"), "just fast-tests", "just lint"])],
                    cases=[{"criterion": "c", "check": self.wrap("c")}])
        got = {part: len(cs) for part, cs, rid in e.repeated_slow(plan)}
        self.assertEqual(got, {"just unity-tests": 3})
        self.assertEqual(e.repeated_slow(dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["just unity-tests", "just unity-tests"])])), [])
        wrapped = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=["mkdir -p ev && just fast-tests > ev/o 2>&1"])])
        self.assertEqual([(p, rid) for p, cs, rid in e.repeated_slow(wrapped)], [])  # not slow by name or history
        e.cfg["checks"][0]["cmd"] = "just unity-tests"
        one = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.wrap("a")])])
        self.assertEqual([(p, rid) for p, cs, rid in e.repeated_slow(one)], [("just unity-tests", "tests")])

    def test_the_plan_is_sent_back_once(self):
        bad = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[self.wrap("a"), self.wrap("b")])])
        rc, s = self.run_engine({"plan": [bad, PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "planner", "worker", "reviewer"])
        self.assertIn("slow commands run in more than one check", s.prompts[1])
        self.assertIn("just unity-tests", s.prompts[1])


class AskText(StagesTest):
    """13.9: a 'needs a human' block is a stuck ask with a readable question, never Right/Wrong over a heredoc."""

    def test_needs_a_human_is_not_a_verify_ask(self):
        why = "needs a human: the write step was denied `{'command': '/bin/zsh -lc \"python3 - <<PY" + "x" * 3000 + "\"'}` and gave no answer"
        self.assertEqual(engine.ask_kind(why), "stuck")
        self.assertEqual(engine.ask_options("stuck", why), [])
        q = engine.human_question(why)
        self.assertLess(len(q), 1200)
        self.assertIn("what to try or what to allow", q)
        self.assertEqual(engine.ask_kind("verify: before land, the workers could not check: x"), "verify")

    def test_a_nothing_proves_block_asks_how_to_prove_it(self):
        why = "the check before land: nothing proves Whether the quoted answers match. after 2 fix rounds: it needs the owner's hint"
        self.assertIn("how to prove it", engine.human_question(why))


if __name__ == "__main__":
    unittest.main()
