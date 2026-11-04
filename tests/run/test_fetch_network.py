"""The engine's initial fetch closes as a cost-free network pause, even repeatedly."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.engine_case import EngineTest

from taskloop.adapters import storm as storm_file
from taskloop.adapters.repourl import repo_url
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import ParkStore
from taskloop.domain import outcome, storm

DNS = "fatal: unable to access 'https://github.com/org/repo': Could not resolve host: github.com"


class InitialFetch(EngineTest):
    def test_repeated_initial_fetch_pauses_charge_no_attempt_failure_label_or_storm(self):
        assert self.sim is not None
        self.sim.fail(("fetch",), DNS)
        with (mock.patch.object(storm_file, "write_storm") as write_storm,
              mock.patch.object(storm, "storm_trip") as storm_trip):
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
            write_storm.assert_not_called()
            storm_trip.assert_not_called()
        assert not [c for c in self.bd_calls if c[:2] == ("label", "add")]
        assert any(c[:1] == ("update",) and "open" in c for c in self.bd_calls)

    def test_network_close_does_not_change_an_existing_storm_record(self):
        assert self.sim is not None
        self.sim.fail(("fetch",), DNS)
        records = []

        def existing(engine):
            path = storm_file.storm_path(engine.home.root, repo_url(engine.git, engine.wt))
            storm_file.write_storm(path, "FAULT_INFRA old", ("old-1", "old-2"), engine.clock.now(),
                                   engine.clock.now(), outcome.KNOBS["storm_window_s"])
            records.append((path, path.read_bytes()))

        self.run_engine({}, prep=existing)
        path, original = records[0]
        assert path.read_bytes() == original
        assert self.eng.result().kind == Kind.PAUSE_NETWORK.value
