"""Shared observation is fenced and read-only, including expired renewal candidates."""

from collections.abc import Generator
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest
from test_recovery import recovery
from test_recovery_registration import WORKER, intended
from test_recovery_snapshot import capture
from test_recovery_store import CHANGES, KEY, OWNED, database, observed

from taskloop.attempt_types import Admission
from taskloop.recovery.models import Claim, Observations, Outcome, Result
from taskloop.slot_lock import SlotBusy, SlotLockUnavailable


@pytest.mark.parametrize("supplied", [False, True])
@pytest.mark.parametrize("expired", [False, True])
def test_observation_holds_custody_without_granting_or_renewing_authority(
    tmp_path: Path, supplied: bool, expired: bool,
) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    app.clock = lambda: 100 if expired else 10
    held = False
    acquisitions = 0

    @contextmanager
    def custody(_admission: Admission) -> Generator[None]:
        nonlocal held, acquisitions
        assert not held
        held = True
        acquisitions += 1
        try:
            yield
        finally:
            held = False

    def claim(_admission: Admission) -> Claim:
        assert held and not con.in_transaction
        return OWNED

    app.custody, app.claim = custody, claim
    before = list(con.iterdump())
    scope = custody(observed(app.store, allow_expired=True).snapshot.attempt.admission) if supplied else nullcontext()
    with scope:
        result = app.observe(KEY, custody=nullcontext() if supplied else None, allow_expired=expired)
    assert isinstance(result, Observations) and result.claim == OWNED
    assert result.snapshot.intent is None and result.snapshot.attempt.admission.deadline == 100
    assert acquisitions == 1 and not held and list(con.iterdump()) == before
    expired_result = app.store.snapshot(KEY, 100)
    assert isinstance(expired_result, Result) and expired_result.outcome is Outcome.EXPIRED
    con.close()


@pytest.mark.parametrize(("change", "outcome"), CHANGES)
@pytest.mark.parametrize("during_read", [False, True])
def test_observation_races_return_explained_refusals_without_authorization(
    tmp_path: Path, change: str, outcome: Outcome, during_read: bool,
) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    saved: list[str] = []

    def changed() -> None:
        assert not con.in_transaction
        con.execute(change)
        saved.extend(con.iterdump())

    @contextmanager
    def custody(_admission: Admission) -> Generator[None]:
        if not during_read:
            changed()
        yield

    def claim(_admission: Admission) -> Claim:
        if during_read:
            changed()
        else:
            raise AssertionError("Drift at custody acquisition must precede world reads")
        return OWNED

    app.custody, app.claim = custody, claim
    result = app.observe(KEY)
    assert isinstance(result, Result) and result.outcome is outcome and result.explanation
    assert list(con.iterdump()) == saved
    con.close()


@pytest.mark.parametrize("during_read", [False, True])
def test_capture_wins_over_observation_and_expiration(tmp_path: Path, during_read: bool) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)
    intent = intended(app.store)
    assert app.store.register(intent, WORKER, lambda: 10).outcome is Outcome.REGISTERED
    snapshot = observed(app.store).snapshot
    saved: list[str] = []

    def claim(_admission: Admission) -> Claim:
        capture(con, snapshot)
        saved.extend(con.iterdump())
        app.clock = lambda: 100
        return OWNED

    if during_read:
        app.claim = claim
    else:
        claim(snapshot.attempt.admission)
    result = app.observe(KEY)
    assert isinstance(result, Result) and result.outcome is Outcome.CAPTURED and result.explanation
    assert list(con.iterdump()) == saved
    con.close()


@pytest.mark.parametrize(("error", "outcome"), [(SlotBusy, Outcome.CUSTODY_BUSY), (SlotLockUnavailable, Outcome.UNAVAILABLE)])
def test_observation_explains_unavailable_custody(tmp_path: Path, error: type[Exception], outcome: Outcome) -> None:
    con = database(tmp_path / "factory.db")
    app = recovery(con)

    @contextmanager
    def custody(_admission: Admission) -> Generator[None]:
        raise error("Custody unavailable")
        yield

    app.custody = custody
    result = app.observe(KEY)
    assert isinstance(result, Result) and result.outcome is outcome and result.explanation
    con.close()
