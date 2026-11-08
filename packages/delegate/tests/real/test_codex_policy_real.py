"""delegate-aam: the reviewer runs Codex at medium effort, the planner stays at high."""

import copy

import routing_support as support
from test_route import CFG, T, accounts

from tltestkit.procsim import real_proc


class CodexPolicy:
    def setup_method(self):
        self.cfg = copy.deepcopy(CFG)
        self.args = {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False, "unattended": True}

    @real_proc("delegate: a worker, git or CLI process")
    def test_reviewer_runs_codex_at_medium_effort_planner_stays_high(self):
        """delegate-aam: medium on every Codex step of the reviewer role (and in the launched command); planner unchanged."""
        r = self.cfg["roles"]["reviewer"]
        steps = [s for v in r["by_author"].values() for s in v if s["on"] == "openai"]
        assert steps
        assert {s["effort"] for s in steps} == {"medium"}
        ls = {"OPENAI_SUBSCRIPTION": accounts()["OPENAI_SUBSCRIPTION"]}
        d = support.decide("reviewer", self.cfg, ls, {}, T, self.args)
        assert d["effort"] == "medium"
        assert "model_reasoning_effort=medium" in d["how"]["cli"]
        p = support.decide("planner", self.cfg, ls, {}, T, self.args)
        assert p["effort"] == "high"
        assert "model_reasoning_effort=high" in p["how"]["cli"]
