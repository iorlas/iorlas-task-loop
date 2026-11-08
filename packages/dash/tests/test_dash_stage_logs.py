"""Stage logs preserve roles, attempts, boundaries and recorded budgets."""

from tlkernel.delegate import LiveMsg
from tltestkit.case import Case

from tldash.testing import RunScript, T
from tldash.views import passes, stage_logs


class StageLogs(Case):
    def test_short_completed_stage_is_done_and_pending_has_no_log(self):
        run = RunScript("b-1").step("plan", 30, outcome="approved").close("done").run(T + 100)
        (p,) = passes.passes_of([run])
        cell = passes.cells_of(p)[0]
        assert (cell.state, cell.secs, cell.outcome) == ("done", 30, "approved")
        logs = stage_logs.logs_of(p, {})
        assert logs[0].roles
        assert logs[1].roles == []

    def test_roles_attempts_live_lines_and_transition_stay_in_their_stage(self):
        s = RunScript("b-1").add("step_start", id="w", step="write")
        for n, role in enumerate(("writer", "writer", "reviewer"), 1):
            s.add("call_start", id=f"c{n}", n=n, step="write", node="w", role=role).wait(10)
            s.add("call_end", id=f"c{n}", status="ok", account="codex", model="model", secs=10)
        s.add("step_end", id="w", step="write", outcome="approved", exec_seconds=30)
        s.add("transition", **{"from": "w", "to": "checks", "cause": "written", "detail": "ready to test"})
        s.step("checks", 10).close("done")
        (p,) = passes.passes_of([s.run(T + 100)])
        logs = stage_logs.logs_of(p, {1: [LiveMsg(t=T + 2, text="first writer")],
                                      2: [LiveMsg(t=T + 12, text="second writer")]})
        roles = logs[1].roles
        assert [r.role for r in roles] == ["writer", "reviewer", "engine"]
        assert [a.id for a in roles[0].attempts] == ["c1", "c2"]
        a = roles[0].attempts[1]
        assert (a.account, a.model, a.t, a.secs, a.outcome) == ("codex", "model", T + 10, 10, "ok")
        assert "second writer" in [ln.text for ln in a.lines]
        assert "first writer" not in [ln.text for ln in a.lines]
        assert "ready to test" in " ".join(ln.text for a in roles[-1].attempts for ln in a.lines)

    def test_recorded_overrun_is_amber_state_with_planned_and_actual(self):
        s = RunScript("b-1").step("review", 90, outcome="approved")
        s.add("overrun", stage="review", budget_s=60, elapsed_s=90).close("done")
        (p,) = passes.passes_of([s.run(T + 100)])
        cell = next(c for c in passes.cells_of(p) if c.phase == "review")
        assert (cell.state, cell.budget_s, cell.secs, cell.outcome) == ("overrun", 60, 90, "approved")

    def test_failed_step_before_a_later_success_stays_failed(self):
        s = RunScript("b-1").step("checks", 10, outcome="red").step("review", 10).close("done")
        (p,) = passes.passes_of([s.run(T + 100)])
        assert next(c.state for c in passes.cells_of(p) if c.phase == "test") == "failed"

    def test_check_tail_and_within_budget_duration_are_recorded(self):
        s = RunScript("b-1").step("checks", 30, outcome="green")
        s.add("checks", node_id="n1", run={"round": 1, "results": [
            {"id": "unit", "cmd": "pytest", "group": "tests", "exit": 0, "status": "passed",
             "tail": "all tests passed", "secs": 30, "wall_min": 1, "track": "unit"}]}).close("done")
        (p,) = passes.passes_of([s.run(T + 100)])
        cell = next(c for c in passes.cells_of(p) if c.phase == "test")
        assert (cell.state, cell.secs, cell.budget_s) == ("done", 30, 60)
        role = next(r for r in stage_logs.logs_of(p, {})[2].roles if r.role == "checks")
        assert role.attempts[0].outcome == "passed"
        assert "all tests passed" in [ln.text for ln in role.attempts[0].lines]

    def test_repeated_phase_in_a_new_pass_does_not_reuse_old_attempts(self):
        s = RunScript("b-1").step("write", 10, 1).step("checks", 10, outcome="red").move("write", "bad_checks")
        s.step("write", 10, 1).close("done")
        first, second = passes.passes_of([s.run(T + 100)])
        old = stage_logs.logs_of(first, {})[1].roles[0].attempts
        new = stage_logs.logs_of(second, {})[1].roles[0].attempts
        assert ([a.id for a in old], [a.id for a in new]) == (["c1"], ["c3"])
