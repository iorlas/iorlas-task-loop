"""Wire permanence reaches durable parks without changing machine repair or exhausted retry asks."""

import sys
from pathlib import Path
from unittest import mock

import pytest
from support.parkmock import through_change

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.app.asks import parks
from taskloop.app.asks.closing import ClosingAsks
from taskloop.app.pipeline.blocked import Blocked, blocked_for
from taskloop.app.pipeline.closing import Closer
from taskloop.app.workers.lane_acts import LaneActs
from taskloop.domain.lanes import policy
from tlkernel import runoutcome as oc
from tlkernel.bead import Bead
from tlkernel.delegate import DelegateResult, Retry, StopFacts
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind


class DelegatePauseFacts(Case):
    def test_unknown_wire_stop_reaches_durable_pause_and_preserves_owner_asks(self):
        bead = Bead(id=BeadId("t-1"), title="work", status="open")
        for permanence in policy.PERMANENCES:
            with self.subTest(permanence=permanence), mock.patch.object(parks, "ParkStore") as store:
                through_change(store)
                retry = Retry(kind="predicted", at=900) if permanence == "transient" else Retry(kind="none")
                result = DelegateResult(stop=StopFacts(reason="future_delegate_reason", scope="machine",
                                                       permanence=permanence, retry=retry))
                stop = policy.stop_of(result)
                assert stop is not None
                action = policy.decide(stop, policy.Ctx())
                assert isinstance(action, policy.Yield)
                host = mock.Mock(dry=False, home=mock.Mock(), bead=bead.id, run_id="r1", asked=False)
                host.cfg.writer_family, host.cfg.second_writer_family, host.plan_data, host.budget.labels = [], "", None, []
                host.clock.now.return_value = 100
                host.ask_flow.raise_ask.return_value = True
                worker = mock.Mock()
                worker.ops.blocked = blocked_for
                call = mock.Mock(role="worker", node="write", counts={"crashes": 0})
                with pytest.raises(Blocked):
                    LaneActs(host, worker).end(call, result, stop, action)
                assert host.pause_permanence == permanence
                store.return_value.get.return_value = None
                with mock.patch("taskloop.app.pipeline.closing.beadtools.peek", return_value=bead):
                    Closer(host, mock.Mock(), ClosingAsks(host.home), ClosingAsks(host.home)).pause(oc.make(Kind.PAUSE_LANE, "paused"))
                saved = store.return_value.put.call_args.args[0]
                assert saved.permanence == permanence
                assert saved.retry_at == (900 if permanence == "transient" else 0)
                assert host.ask_flow.raise_ask.call_count == int(permanence == "needs_owner")
