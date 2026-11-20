"""Recovery claim observations use only the explicitly bound tracker's read seam."""

from pathlib import Path

import pytest
from beads_client import BdError, Bead
from beads_client.testing import FakeTaskReadClient
from test_recovery_store import KEY, database

from taskloop import tracker_client
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Admission
from taskloop.recovery.models import ClaimState
from taskloop.tracker import ACTOR


@pytest.fixture
def admission(tmp_path: Path) -> Admission:
    con = database(tmp_path / "factory.db")
    record = AttemptStore(lambda: con).load(KEY)
    assert record is not None
    con.close()
    return record.admission


@pytest.mark.parametrize(("status", "assignee", "state"), [
    ("open", ACTOR, ClaimState.OWNED), ("in_progress", ACTOR, ClaimState.OWNED),
    ("closed", ACTOR, ClaimState.LOST), ("open", "", ClaimState.LOST), ("open", "someone", ClaimState.LOST),
    ("", ACTOR, ClaimState.UNKNOWN),
])
def test_bound_read_explains_claim_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admission: Admission, status: str, assignee: str, state: ClaimState,
) -> None:
    client = FakeTaskReadClient((Bead("tl-1", status=status, assignee=assignee),))
    roots: list[Path] = []

    def reader(root: Path) -> FakeTaskReadClient:
        roots.append(root)
        return client

    monkeypatch.setattr(tracker_client, "_reader", reader)
    result = tracker_client.tracker_recovery_claim(tmp_path)(admission)
    assert result.state is state and result.explanation
    assert roots == [tmp_path.resolve()] and client.reads == ["tl-1"]


@pytest.mark.parametrize("missing", [False, True])
def test_absence_and_failed_reads_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admission: Admission, missing: bool,
) -> None:
    client = FakeTaskReadClient(faults={} if missing else {"tl-1": BdError("timeout", "Task read timed out")})
    monkeypatch.setattr(tracker_client, "_reader", lambda _root: client)
    result = tracker_client.tracker_recovery_claim(tmp_path)(admission)
    assert result.state is (ClaimState.LOST if missing else ClaimState.UNKNOWN) and result.explanation
    assert client.reads == ["tl-1"]


def test_invalid_binding_is_unknown_without_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admission: Admission,
) -> None:
    def forbidden(_root: Path) -> FakeTaskReadClient:
        raise AssertionError("An invalid binding must not read a tracker")

    monkeypatch.setattr(tracker_client, "_reader", forbidden)
    result = tracker_client.tracker_recovery_claim(tmp_path / "missing")(admission)
    assert result.state is ClaimState.UNKNOWN and result.explanation
