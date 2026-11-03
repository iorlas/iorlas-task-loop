"""Invalid reviews retry through delegate, then leave an unavailable review while the stage continues."""
from unittest import mock

from support import fake_route
from support.builders import make_engine, plan_of
from support.engine_case import BEAD, CLEAN, PLAN, WRITE, EngineTest, stop
from support.fakes import FakeClock
from support.logs import records

from taskloop.app.write.state import StageState
from taskloop.contracts.enums import Outcome
from taskloop.contracts.kinds import Kind


class ReviewInvalid(EngineTest):
    def go(self, reviews, *, node="review"):
        clock = FakeClock()
        started = clock.now()

        def answer(value):
            def reply(script, called, cwd, resume):
                clock.advance(60)
                return value
            return reply

        answers: dict[str, list] = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}
        answers[node] = [answer(value) for value in reviews]
        script = fake_route.Script(answers)
        with self.store.stub(show=BEAD):
            self.eng = make_engine(self.wt, script=script, store=self.store, clock=clock, cfg={"reflect": False})
            rc = self.eng.run()
        self.assertEqual(clock.now() - started, 120)
        self.assertEqual(script.nodes.count(node), 2)
        return rc, script

    def review_ends(self):
        return [r for r in records(self.eng, "step_end") if r["step"] == "review"]

    def test_invalid_then_valid_retries_delegate_and_accepts_the_valid_review(self):
        rc, script = self.go([stop("schema_invalid"), CLEAN])
        self.assertEqual(rc, 0)
        self.assertEqual(script.nodes, ["plan", "write", "review", "review"])
        self.assertEqual([r["outcome"] for r in self.review_ends()], ["clean"])
        self.assertFalse(self.eng.lane_notes)
        self.assertEqual(self.eng.stats["rounds"], 0)
        retries = records(self.eng, "retry_decision")
        self.assertEqual([(r["action"], r["reason"]) for r in retries], [("new_thread", "schema_invalid")])
        self.assertIsNone(script.calls[-1][1])

    def test_invalid_every_time_continues_with_unavailable_in_outcome_and_dashboard_data(self):
        rc, script = self.go([stop("schema_invalid"), stop("schema_invalid")])
        self.assertEqual(rc, 0)
        self.assertEqual(script.nodes, ["plan", "write", "review", "review"])
        self.assertEqual(self.eng.stats["rounds"], 0)
        ends = self.review_ends()
        self.assertEqual([r["outcome"] for r in ends], ["unavailable"])
        self.assertIn("schema_invalid", ends[0]["detail"])
        trace = self.eng.stores.traces.read_from(0).items[-1].rec
        self.assertEqual(trace.outcome, Outcome.LANDED)
        self.assertEqual(len(trace.lane_notes), 1)
        self.assertIn("review unavailable", trace.lane_notes[0])
        self.assertIn("schema_invalid", trace.lane_notes[0])
        self.assertTrue(any("Review (engine):" in c[3] and "review unavailable" in c[3]
                            for c in self.store.said("comments", "add")))
        transitions = records(self.eng, "transition")
        self.assertTrue(any(r["cause"] == "review_unavailable" and r["to"] == "next" for r in transitions))

    def test_other_review_failures_still_fail_the_run(self):
        rc, _ = self.go([stop("worker_failed"), stop("worker_failed")])
        self.assertEqual(rc, 2)
        self.assertEqual(self.eng.kind, Kind.FAULT_INFRA)
        self.assertFalse(self.eng.lane_notes)
        self.assertFalse(any(r["outcome"] == "unavailable" for r in self.review_ends()))

    def test_invalid_writer_still_fails_the_run(self):
        rc, _ = self.go([stop("schema_invalid"), stop("schema_invalid")], node="write")
        self.assertEqual(rc, 2)
        self.assertEqual(self.eng.kind, Kind.FAULT_INFRA)
        self.assertFalse(self.eng.lane_notes)

    def test_unavailable_review_keeps_existing_and_writer_unchecked_items(self):
        earlier = {"what": "earlier stage needs verification", "kind": "requirement"}
        written = {"what": "this stage needs verification", "kind": "requirement"}
        e = self.checks_engine(attrs={"unchecked": [earlier]})
        s = StageState(plan_of(PLAN), 0, None)
        s.wrote_unchecked = [earlier, written]
        with mock.patch.object(e.checkpoints, "keep_pending"):
            e.stage_loop.reviewing.unavailable(s)
        self.assertEqual(e.unchecked, [earlier, written])
