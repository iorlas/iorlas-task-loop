"""Owner requests act once at safe run boundaries, using signal rows and a small host."""
from dataclasses import dataclass, field

import pytest

from taskloop.app.pipeline.blocked import Blocked
from taskloop.app.pipeline.requests import NOTE_HEAD, OwnerRequests, peek
from taskloop.contracts import log as rec
from taskloop.contracts.kinds import Kind
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.requests import OwnerNote, OwnerRequest
from taskloop.contracts.signalrows import SignalRows


@dataclass
class Halt:
    calls: int = 0

    def set(self) -> None:
        self.calls += 1


@dataclass
class Log:
    rows: list[rec.Said] = field(default_factory=list)

    def emit(self, record: rec.Said) -> int:
        self.rows.append(record)
        return len(self.rows)


@dataclass
class Steps:
    moves: list[tuple[str, str, str]] = field(default_factory=list)

    def move(self, to: str, cause: str, detail: str = "") -> None:
        self.moves.append((to, cause, detail))


@dataclass
class Host:
    home: ConfigDir
    run_id: str = "run"
    halt: Halt = field(default_factory=Halt)
    log: Log = field(default_factory=Log)
    steps: Steps = field(default_factory=Steps)

    def step_id(self) -> str:
        return "n1"

    def halt_point(self) -> None:
        raise AssertionError("unexpected halt boundary")


@pytest.fixture
def host(workdir):
    return Host(ConfigDir(workdir))


def test_beat_sets_halt_only_for_stop_and_only_once(host):
    side = OwnerRequests(host)
    rows = SignalRows(host.home, host.run_id)
    side.at_beat()
    rows.post(OwnerRequest(park=True), 1)
    side.at_beat()
    assert host.halt.calls == 0
    rows.post(OwnerRequest(stop=True), 2)
    side.at_beat()
    side.at_beat()
    assert side.stopped
    assert host.halt.calls == 1
    assert peek(host.home, host.run_id) is not None


def test_step_park_moves_then_raises_owner_park(host):
    side = OwnerRequests(host)
    SignalRows(host.home, host.run_id).post(OwnerRequest(park=True), 1)
    with pytest.raises(Blocked) as stopped:
        side.at_step("write")
    assert stopped.value.kind is Kind.OWNER_PARK
    assert host.steps.moves == [("pause", "owner_park", "the owner parked it before write")]
    assert peek(host.home, host.run_id) is None
    assert host.halt.calls == 0


def test_notes_accumulate_and_prompt_tail_consumes_once(host):
    side = OwnerRequests(host)
    rows = SignalRows(host.home, host.run_id)
    rows.post(OwnerRequest(notes=[OwnerNote(text="one", t=1, by="owner")]), 1)
    side.at_step("plan")
    rows.post(OwnerRequest(notes=[OwnerNote(text="two", t=2, by="owner")]), 2)
    side.at_step("write")
    assert side.prompt_tail() == NOTE_HEAD + "- one\n- two\n"
    assert side.prompt_tail() == ""
    assert [(row.step, row.who, row.text) for row in host.log.rows] == [("n1", "owner", "one"), ("n1", "owner", "two")]


def test_drop_discards_pending_and_closed_boundaries_take_nothing(host):
    side = OwnerRequests(host)
    rows = SignalRows(host.home, host.run_id)
    rows.post(OwnerRequest(park=True), 1)
    side.drop()
    assert peek(host.home, host.run_id) is None
    rows.post(OwnerRequest(stop=True, park=True), 2)
    side.at_beat()
    side.at_step("close")
    assert peek(host.home, host.run_id) is not None
    assert host.halt.calls == 0
    assert host.steps.moves == []
    assert side.prompt_tail() == ""
