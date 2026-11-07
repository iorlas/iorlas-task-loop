"""A terminal invalid review leaves an unavailable review while the stage continues."""
from unittest import mock

from support import fake_route
from support.builders import make_engine
from support.cfgs import plan_of
from support.engine_case import EngineTest, stop
from support.fakes import FakeClock
from support.logs import records
from support.plans import BEAD, CLEAN, PLAN, WRITE

from taskloop.app.write.state import StageState
from tlkernel.enums import Outcome
from tlkernel.kinds import Kind


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
        assert clock.now() - started == 60
        assert script.nodes.count(node) == 1
        return rc, script

    def review_ends(self):
        return [r for r in records(self.eng, "step_end") if r["step"] == "review"]

    def test_invalid_review_is_terminal_even_if_a_valid_review_would_follow(self):
        rc, script = self.go([stop("schema_invalid"), CLEAN])
        assert rc == 0
        assert script.nodes == ["plan", "write", "review"]
        assert [r["outcome"] for r in self.review_ends()] == ["unavailable"]
        assert len(self.eng.write.lane_notes) == 1
        assert self.eng.stats["rounds"] == 0
        decisions = records(self.eng, "retry_decision")
        assert [(r["action"], r["reason"]) for r in decisions] == [("fault", "schema_invalid")]

    def test_invalid_review_continues_with_unavailable_in_outcome_and_dashboard_data(self):
        rc, script = self.go([stop("schema_invalid")])
        assert rc == 0
        assert script.nodes == ["plan", "write", "review"]
        assert self.eng.stats["rounds"] == 0
        ends = self.review_ends()
        assert [r["outcome"] for r in ends] == ["unavailable"]
        assert "schema_invalid" in ends[0]["detail"]
        trace = self.eng.stores.traces.read_from(0).items[-1].rec
        assert trace.outcome == Outcome.LANDED
        assert len(trace.lane_notes) == 1
        assert "review unavailable" in trace.lane_notes[0]
        assert "schema_invalid" in trace.lane_notes[0]
        assert any("Review (engine):" in c[3] and "review unavailable" in c[3]
                            for c in self.store.said("comments", "add"))
        transitions = records(self.eng, "transition")
        assert any(r["cause"] == "review_unavailable" and r["to"] == "next" for r in transitions)

    def test_other_review_failures_still_fail_the_run(self):
        rc, _ = self.go([stop("worker_failed")])
        assert rc == 2
        assert self.eng.kind == Kind.FAULT_INFRA
        assert not self.eng.write.lane_notes
        assert not any(r["outcome"] == "unavailable" for r in self.review_ends())

    def test_invalid_writer_still_fails_the_run(self):
        rc, _ = self.go([stop("schema_invalid")], node="write")
        assert rc == 2
        assert self.eng.kind == Kind.FAULT_INFRA
        assert not self.eng.write.lane_notes

    def test_unavailable_review_keeps_existing_and_writer_unchecked_items(self):
        earlier = {"what": "earlier stage needs verification", "kind": "requirement"}
        written = {"what": "this stage needs verification", "kind": "requirement"}
        e = self.checks_engine(attrs={"unchecked": [earlier]})
        s = StageState(plan_of(PLAN), 0, None)
        s.wrote_unchecked = [earlier, written]
        with mock.patch.object(e.checkpoints, "keep_pending"):
            e.stage_loop.reviewing.unavailable(s)
        assert e.review.unchecked == [earlier, written]
