"""Recorded stage-log examples for the dashboard contract and browser checks."""

from taskloop.contracts import dash as D


def attempt(id: str, text: str, t: float) -> D.StageAttempt:
    return D.StageAttempt(id=id, t=t, secs=30.0, outcome="ok", lane="codex", model="fixture-model",
                          lines=[D.TermLine(t=t, text=text)])


def stage_passes(bead: str, passes: list[D.Pass], now: float) -> list[D.Pass]:
    if bead != "lifesim-6dq0":
        return passes
    first = passes[0]
    first = first.replace(cells=[c.replace(state="overrun", budget_s=3000.0) if c.phase == D.Phase.WRITE else c for c in first.cells],
                          logs=[D.StageLog(phase=D.Phase.PLAN, roles=[D.StageRole(role="planner", attempts=[
                              attempt("p1", "plan: 3 steps", now - 7000)])]),
                                D.StageLog(phase=D.Phase.WRITE, roles=[
                                    D.StageRole(role="writer", attempts=[attempt("w1", "first write", now - 6000),
                                                                         attempt("w2", "fixed weather_tick", now - 5000)]),
                                    D.StageRole(role="reviewer", attempts=[attempt("r1", "approved", now - 4000)])])])
    live = D.StageAttempt(id="live-write", t=now - 100, secs=100.0, outcome="running", live=True, lane="codex", model="fixture-model",
                         lines=[D.TermLine(t=now - 12 + i, text=f"stage terminal line {i} " + "long output " * 20) for i in range(13)])
    return [first, passes[1].replace(logs=[D.StageLog(phase=D.Phase.WRITE, roles=[D.StageRole(role="writer", attempts=[live])])])]
