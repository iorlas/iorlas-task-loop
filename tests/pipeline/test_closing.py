"""The close lints asks and records pauses through supplied ports."""
from unittest.mock import Mock

from support.narrow_hosts import CloseKit
from support.pipeline_ports import FakeAskRules, FakeParkBook

from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.parks import Park
from taskloop.domain import outcome as oc
from taskloop.domain.asks import specs


def test_ask_lint_converts_invalid_ask_to_engine_fault(monkeypatch):
    kit = CloseKit()
    rules = FakeAskRules(['missing decision'])
    kit.closer.rules = rules
    finish = Mock()
    monkeypatch.setattr(kit.closer, 'finish', finish)
    spec = specs.plan_noop('t-1', 'summary')
    kit.closer.run(oc.make(Kind.ASK_STUCK, 'question', spec=spec))
    assert rules.calls == [spec]
    done = finish.call_args.args[0]
    assert done.kind is Kind.FAULT_ENGINE
    assert 'ask_lint: missing decision' in done.detail


def test_pause_passes_run_facts_without_home(monkeypatch):
    kit = CloseKit(dry=False)
    parks = FakeParkBook()
    kit.closer.parks = parks
    bead = Bead(id=BeadId('t-1'), title='work', status='open')
    monkeypatch.setattr('taskloop.app.pipeline.closing.beadtools.peek', lambda *args: bead)
    kit.closer.pause(oc.make(Kind.PAUSE_LANE, 'paused'))
    assert len(parks.paused_calls) == 1
    call = parks.paused_calls[0]
    assert call[:4] == (bead, Kind.PAUSE_LANE, kit.host.run_id, kit.host.clock.now())


def test_dry_pause_does_not_call_park_book():
    kit = CloseKit()
    parks = FakeParkBook()
    kit.closer.parks = parks
    kit.closer.pause(oc.make(Kind.PAUSE_LANE, 'paused'))
    assert parks.paused_calls == []


def test_pause_applies_the_park_books_retry_and_reason(monkeypatch):
    kit = CloseKit(dry=False)
    bead = Bead(id=BeadId('t-1'), title='work', status='open')
    rec = Park(bead=bead.id, hash='hash', runs=1, run=kit.host.run_id, t=100,
               reason='no_lane', retry_at=500, permanence='transient')
    kit.closer.parks = FakeParkBook(rec)
    monkeypatch.setattr('taskloop.app.pipeline.closing.beadtools.peek', lambda *args: bead)
    kit.closer.pause(oc.make(Kind.PAUSE_LANE, 'paused'))
    assert kit.host.retry_after == 500
    assert kit.host.pause_reason == 'no_lane'
    assert not kit.host.asked
