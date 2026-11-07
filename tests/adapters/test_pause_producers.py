"""Locally synthesized no-answer stops retain engine provenance through the lane exit."""
import sys
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters import delegate, delegate_wire
from taskloop.app.pipeline.blocked import Blocked, blocked_for
from taskloop.app.workers.lane_acts import LaneActs
from taskloop.domain.lanes import pauses, policy
from tlkernel.delegate import RunRequest


class PauseProducers(Case):
    def test_spawn_failure_and_missing_answer_keep_engine_provenance(self):
        resolved = delegate.Resolved(Path("."), "route.py", {}, "explicit")
        request = RunRequest(role="worker", brief_path="", schema_path="", cwd=".")
        runners = (mock.Mock(side_effect=OSError("spawn failed")), mock.Mock(return_value=mock.Mock(stdout="", stderr="", returncode=1)))
        for runner in runners:
            with self.subTest(runner=runner):
                answer = delegate.call(resolved, request, "work", {}, runner, {})
                stop = policy.stop_of(answer.res)
                assert stop is not None
                assert (stop.reason, stop.producer) == ("no_answer", "engine")
                assert pauses.rule(stop.reason, stop.producer).permanence == "transient"

    def test_lane_exit_uses_stop_producer_for_synthetic_and_wire_stops(self):
        for producer in ("engine", "delegate"):
            with self.subTest(producer=producer):
                result = delegate_wire.synth("no_answer", "machine", "transient", "no answer")
                assert result.stop is not None
                result = result.replace(stop=result.stop.replace(producer=producer))
                stop = policy.stop_of(result)
                assert stop is not None
                host = mock.Mock()
                host.cfg.writer_family, host.cfg.second_writer_family, host.plan_data, host.budget.labels = [], "", None, []
                host.clock.now.return_value = 100
                call = mock.Mock(role="worker", node="write", counts={"crashes": 0})
                worker = mock.Mock()
                worker.ops.blocked = blocked_for
                worker.ops.stop_why.return_value = "paused"
                with pytest.raises(Blocked):
                    LaneActs(host, worker).end(call, result, stop, policy.Yield("PAUSE_LANE"))
                assert (host.pause_reason, host.pause_producer) == ("no_answer", producer)
