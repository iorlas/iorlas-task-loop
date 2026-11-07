"""Pipeline recording fakes structurally implement each closing capability."""
from support.pipeline_ports import FakeAskRules, FakeBeadClosing, FakeFollowUps, FakeLandCleanup, FakeParkBook, FakeSlotting

from taskloop.app.pipeline.ports import AskRules, BeadClosing, FollowUps, LandCleanup, ParkBook, Slotting
from taskloop.domain.asks.spec import AskSpec
from tlkernel import fence
from tlkernel.askenums import AskClass
from tlkernel.bead import Bead
from tlkernel.enums import Outcome
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.parks import Park


def test_ask_rules():
    fake = FakeAskRules(["invalid"])
    rules: AskRules = fake
    spec = AskSpec(ask_class=AskClass.OPEN_QUESTION, decision="")
    assert rules.problems(spec) == ["invalid"]
    assert fake.calls == [spec]


def test_park_book():
    bead = Bead(id=BeadId("t-1"), title="work", status="open")
    result = Park(bead=bead.id, hash="hash", runs=1, run="run-1", t=1.0)
    fake = FakeParkBook(result)
    book: ParkBook = fake
    assert book.paused(bead, Kind.PAUSE_NETWORK, "run-1", 1.0, reason="network",
                       not_before=2.0, fingerprint="fp") is result
    book.ended(bead, Kind.DONE, "run-1", 3.0)
    assert fake.paused_calls == [(bead, Kind.PAUSE_NETWORK, "run-1", 1.0, "network", 2.0, "fp", None, None)]
    assert fake.ended_calls == [(bead, Kind.DONE, "run-1", 3.0)]


def test_followups():
    result = [{"title": "leftover"}]
    fake = FakeFollowUps(result)
    followups: FollowUps = fake
    assert followups.file() is result
    assert fake.calls == [()]


def test_land_cleanup():
    fake = FakeLandCleanup()
    cleanup: LandCleanup = fake
    cleanup.retry("repo")
    assert fake.calls == ["repo"]


def test_bead_closing():
    fake = FakeBeadClosing(close_result=2, block_result=3)
    closing: BeadClosing = fake
    claim = fence.offline(BeadId("t-1"))
    said: list[str] = []
    assert closing.close(claim, None) == 2
    assert closing.block(claim, "stuck", said.append) == 3
    assert fake.close_calls == [(claim, None)]
    assert fake.block_calls == [(claim, "stuck", said.append)]


def test_slotting():
    fake = FakeSlotting()
    slotting: Slotting = fake
    slotting.leave_slot(Outcome.LANDED, "task/topic")
    assert fake.calls == [(Outcome.LANDED, "task/topic")]
