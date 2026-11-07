"""The engine's initial fetch closes as a cost-free network pause, even repeatedly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.engine_case import EngineTest

from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import ParkStore

DNS = "fatal: unable to access 'https://github.com/org/repo': Could not resolve host: github.com"


class InitialFetch(EngineTest):
    def test_repeated_initial_fetch_pauses_charge_no_attempt_failure_label(self):
        assert self.sim is not None
        self.sim.fail(("fetch",), DNS)
        for _ in range(4):
            rc, script = self.run_engine({})
            assert rc == 2
            assert script.nodes == []
            assert self.eng.done == []
            result = self.eng.result()
            assert (result.outcome, result.kind) == ("paused", Kind.PAUSE_NETWORK.value)
            assert not result.asked
            rec = ParkStore(self.eng.home).get(BeadId("t-1"))
            assert rec is not None
            assert (rec.attempts, rec.runs, rec.permanence) == ({}, 0, "transient")
            assert (self.eng.stats["rounds"], self.eng.stats["replans"]) == (0, 0)
            assert (self.blocked, self.ask()) == ([], None)
        assert not [c for c in self.bd_calls if c[:2] == ("label", "add")]
        assert any(c[:1] == ("update",) and "open" in c for c in self.bd_calls)

