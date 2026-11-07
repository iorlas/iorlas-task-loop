"""Settling uses closing capabilities and leaves machine faults open."""
import pytest
from support.narrow_hosts import FakeSettleHost
from support.pipeline_ports import FakeBeadClosing, FakeParkBook

from taskloop.adapters import beadtools
from taskloop.app.pipeline.closing_settle import Settle
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs
from tlkernel.bead import Bead
from tlkernel.kinds import Kind


@pytest.mark.parametrize(('kind', 'reason'), [
    (Kind.LANDED, 'merged abcdef123456 to main: shipped; stats'),
    (Kind.DONE, 'done with nothing to land: shipped'),
])
def test_finished_closes_with_reason_and_ends_park(kind, reason, monkeypatch):
    host = FakeSettleHost()
    host.plan_summary = 'shipped'
    bead = Bead(id=host.bead, title='work', status='in_progress')
    host.store.beads[host.bead] = bead
    beads, parks = FakeBeadClosing(), FakeParkBook()
    monkeypatch.setattr('taskloop.app.pipeline.closing_settle.time.time', lambda: 1000.0)
    Settle(host, beads, parks, beadtools.peek, beadtools.attempt).run(oc.make(kind, sha='abcdef1234567890'), 'stats')
    assert beads.close_calls == [(host.claim, reason)]
    assert beads.block_calls == []
    assert parks.ended_calls == [(bead, kind, host.run_id, 1000.0)]


def test_task_fault_blocks_with_question():
    host = FakeSettleHost()
    beads, parks = FakeBeadClosing(), FakeParkBook()
    spec = specs.repeated_fault(3, 'broken')
    Settle(host, beads, parks, beadtools.peek, beadtools.attempt).run(oc.make(Kind.ASK_STUCK, 'stuck', spec=spec), '')
    assert beads.block_calls == [(host.claim, 'stuck\n\nQuestion: ' + spec.decision, host.comment)]
    assert beads.close_calls == []


def test_machine_fault_releases_claim_without_closing_or_blocking():
    done = oc.make(Kind.FAULT_INFRA, 'disk full')
    host = FakeSettleHost(oc.apply(done, 't-1', [], 1000.0))
    host.store.beads[host.bead] = Bead(id=host.bead, title='work', status='in_progress', assignee=host.claim.actor)
    beads, parks = FakeBeadClosing(), FakeParkBook()
    Settle(host, beads, parks, beadtools.peek, beadtools.attempt).run(done, '')
    held = host.store.beads[host.bead]
    assert (held.status, held.assignee) == ('open', '')
    assert beads.close_calls == beads.block_calls == []
    assert parks.ended_calls[0][:3] == (held, done.kind, host.run_id)
