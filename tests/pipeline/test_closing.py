"""The close lints asks and records pauses through supplied ports."""
from unittest.mock import Mock

import pytest
from support.narrow_hosts import CloseKit

from tlkernel import askspecs as specs
from tlkernel import runoutcome as oc
from tlkernel import wire
from tlkernel.bead import Bead
from tlkernel.checkpoint import Checkpoint, CloseIntent, EndRec, PauseFacts
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import Park
from tlpipeline.testing import FakeAskRules, FakeParkBook


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
    monkeypatch.setattr(kit.closer, 'peek', lambda *args: bead)
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
    monkeypatch.setattr(kit.closer, 'peek', lambda *args: bead)
    kit.closer.pause(oc.make(Kind.PAUSE_LANE, 'paused'))
    assert kit.host.retry_after == 500
    assert kit.host.pause_reason == 'no_lane'
    assert not kit.host.asked


def test_close_intent_round_trips_inside_checkpoint():
    intent = CloseIntent(outcome=EndRec(run="dead", kind="engine_crash", fingerprint="fp", detail="crashed"),
                         pause=PauseFacts(reason="crash", producer="delegate", permanence="transient",
                                          retry_after=1234, crash_fingerprint="dead-fp", crash_site="write"),
                         stats="cost=$9.50; minutes=12", plan_summary="dead plan", asked=True)
    ck = Checkpoint(bead="t-1", run="dead", t=100, ended=intent)
    assert wire.load(Checkpoint, wire.dump(ck)) == ck


def test_resume_restores_dead_runs_pause_and_passes_stats_unchanged(monkeypatch):
    kit = CloseKit(dry=False)
    parks = FakeParkBook()
    kit.closer.parks = parks
    bead = Bead(id=BeadId("t-1"), title="work", status="open")
    monkeypatch.setattr(kit.closer, "peek", lambda *args: bead)
    intent = CloseIntent(outcome=EndRec(run="dead", kind=Kind.ENGINE_CRASH.value, fingerprint="fp", detail="crashed"),
                         pause=PauseFacts(reason="dead reason", producer="delegate", permanence="transient",
                                          retry_after=1234, crash_fingerprint="dead-fp", crash_site="write"),
                         stats="cost=$9.50; minutes=12", plan_summary="dead plan", asked=True)
    finish = Mock(side_effect=lambda done, stats: kit.closer.pause(done))
    monkeypatch.setattr(kit.closer, "finish", finish)
    kit.closer.resume(Checkpoint(bead="t-1", run="dead", t=100, ended=intent))
    assert finish.call_args.args[1] == intent.stats
    assert parks.paused_calls[0][4:] == ("dead reason", 1234, "dead-fp", "delegate", "transient")
    assert kit.host.crash_site == "write"
    assert kit.host.plan_summary == "dead plan"
    assert kit.host.asked


@pytest.mark.parametrize("kind", [Kind.ASK_STUCK, Kind.FAULT_INFRA, Kind.LANDED])
def test_non_pause_does_not_call_park_book(kind):
    kit = CloseKit(dry=False)
    parks = FakeParkBook()
    kit.closer.parks = parks
    kit.closer.pause(oc.make(kind, "done", spec=specs.plan_noop("t-1", "summary") if kind is Kind.ASK_STUCK else None))
    assert parks.paused_calls == []
