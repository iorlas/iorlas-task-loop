"""The gate's recording fakes implement its host protocols."""
from tlkernel.log import Note
from tlkernel.waitenums import WaitWhat

from tlgate.host import CheckSteps, WaitsView
from tlgate.ports import GateLog, GateStores
from tlgate.testing import FakeGateLog, FakeGateStores, FakeSteps, RecordedWaits


def test_log_records_offsets_and_shared_ids() -> None:
    fake = FakeGateLog()
    log: GateLog = fake
    assert log.emit(Note(text="first")) == 0
    assert log.note("second") == 1
    assert fake.records == [Note(text="first"), Note(text="second")]
    assert [log.next_id("c"), log.next_id("w"), log.next_id("c")] == ["c1", "w2", "c3"]


def test_steps_record_calls() -> None:
    fake = FakeSteps("step-1")
    steps: CheckSteps = fake
    steps.begin("check", "running", round=2)
    steps.outcome("pass")
    assert steps.id == "step-1"
    assert fake.calls == [("begin", ("check", "running"), {"round": 2}), ("outcome", ("pass", ""), {})]


def test_stores_cache_by_key() -> None:
    stores: GateStores = FakeGateStores()
    assert stores.results("repo", "check") is stores.results("repo", "check")
    assert stores.results("repo", "check") is not stores.results("other", "check")
    assert stores.results("repo", "check") is not stores.results("repo", "other")
    assert stores.base_red("repo") is stores.base_red("repo")
    assert stores.base_red("repo") is not stores.base_red("other")
    assert stores.check_run("run", None) is stores.check_run("run", None)
    assert stores.check_run("run", None) is not stores.check_run("run", 1)
    assert stores.host.get() is None
    assert stores.durations.keys() == []


def test_waits_record_reports() -> None:
    fake = RecordedWaits()
    waits: WaitsView = fake
    assert waits.start(WaitWhat.ACCOUNT) == "w0"
    waits.note_slot_waits("slot", 1.5)
    waits.add(2.5, WaitWhat.ACCOUNT)
    assert fake.seen == [("slot", 1.5), ("account", 2.5)]
    assert waits.start(WaitWhat.ACCOUNT) == "w2"


def test_leases_release_for_reuse() -> None:
    stores: GateStores = FakeGateStores()
    with stores.leases.acquire("check", 1, timeout=0) as held:
        assert held.name == "check"
        assert held.slot == 0
    with stores.leases.acquire("check", 1, timeout=0) as again:
        assert again.slot == 0
