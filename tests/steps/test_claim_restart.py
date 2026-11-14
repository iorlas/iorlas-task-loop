"""Intact-database claim recovery uses durable intents, ownership observations and fenced adoption."""

import sqlite3
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import PinnedViews
from git_porcelain.testing import FakeRepo
from sqlite_store import Store
from test_admit import Tracker, admission, request, slots, tasks

from taskloop.admit import Admitted
from taskloop.attempt_store import AttemptStore
from taskloop.drain.drain import Ports, reconcile_claims
from taskloop.drain.models import Action, ActionKind, ActionState, Conclusion, Identity, Owner, Role, Seen, State
from taskloop.drain.reconcile import Reconcile
from taskloop.drain.store import DrainStore
from taskloop.factory_schema import SCHEMA
from taskloop.ids import NativeIds
from taskloop.land_store import LandStore

OLD = Identity(pid=101, pgid=101, start="admission", boot="boot")
NEW = Identity(pid=102, pgid=102, start="restart", boot="boot")


def connect(path: Path) -> sqlite3.Connection:
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    return con


def ports(con: sqlite3.Connection, repo: FakeRepo, return_claim: Callable[[Action], bool]) -> Ports:
    reconcile = Reconcile(AttemptStore(lambda: con), LandStore(lambda: con), PinnedViews(repo), tasks, return_claim, lambda: 20)
    return Ports(
        DrainStore(lambda: con, ids=NativeIds()),
        lambda: (Owner(subject="existing-attempt", role=Role.ENTRY, identity=NEW),),
        lambda owner: Seen.ALIVE if owner.identity == NEW else Seen.GONE,
        reconcile,
        lambda _seconds: pytest.fail("claim recovery must not wait"),
        me=lambda: NEW,
    )


@pytest.mark.parametrize("acquired", [False, True])
def test_crashed_admission_reopens_and_admits_without_retake(
    tmp_path: Path, repo: FakeRepo, root: Path, acquired: bool,
) -> None:
    path = tmp_path / "factory.db"
    con = connect(path)
    slots(con, repo, root, 1)
    tracker = Tracker(con, tmp_path / "artifacts")
    claimed = {"unrelated"}

    def crash() -> None:
        if acquired:
            claimed.add("tl-1")
        raise RuntimeError("admission process disappeared during claim acquisition")

    tracker.during = crash
    with pytest.raises(RuntimeError, match="process disappeared"):
        admission(con, tmp_path, tracker, repo).admit(request(tmp_path, repo))
    original = DrainStore(lambda: con, ids=NativeIds()).pending()
    assert len(original) == 1 and original[0].kind is ActionKind.CLAIM
    assert AttemptStore(lambda: con).attempts("tasks", "tl-1") == ()
    con.close()
    con = connect(path)
    recovering = ports(con, repo, lambda _action: False)

    def return_claim(action: Action) -> bool:
        assert not con.in_transaction
        assert recovering.store.pending()[0] == action and action.owner == NEW
        assert recovering.store.adopt(original[0], OLD) is None
        assert reconcile_claims(recovering).conclusion is Conclusion.WAITING
        claimed.discard(action.subject)
        return True

    try:
        recovering = ports(con, repo, return_claim)
        # Reconcile is the production operation, with only its external claim port replaced.
        result = reconcile_claims(recovering)
        assert result.conclusion is Conclusion.COMPLETE and not recovering.store.pending()
        assert recovering.store.boundary().state is State.OPEN and claimed == {"unrelated"}
        tracker = Tracker(con, tmp_path / "artifacts")
        assert isinstance(admission(con, tmp_path, tracker, repo).admit(request(tmp_path, repo)), Admitted)
    finally:
        con.close()


def test_crash_after_release_is_observed_again_without_repeating_the_release(tmp_path: Path, repo: FakeRepo) -> None:
    path = tmp_path / "factory.db"
    con = connect(path)
    gate = DrainStore(lambda: con, ids=NativeIds())
    assert gate.authorize(ActionKind.CLAIM, OLD, subject="tl-1", backlog="tasks", tracker_root="/tracker")
    claimed, releases = {"tl-1"}, []

    def release(action: Action) -> bool:
        if action.subject in claimed:
            claimed.remove(action.subject)
            releases.append(action.subject)
            raise RuntimeError("crash after release")
        return True

    with pytest.raises(RuntimeError, match="after release"):
        reconcile_claims(ports(con, repo, release))
    con.close()
    con = connect(path)
    try:
        recovering = replace(ports(con, repo, release), observe=lambda _owner: Seen.GONE)
        assert reconcile_claims(recovering).conclusion is Conclusion.COMPLETE
        assert not recovering.store.pending() and releases == ["tl-1"]
    finally:
        con.close()


def test_uncertain_tracker_result_stays_durable_until_a_later_restart(tmp_path: Path, repo: FakeRepo) -> None:
    path = tmp_path / "factory.db"
    con = connect(path)
    gate = DrainStore(lambda: con, ids=NativeIds())
    assert gate.authorize(ActionKind.CLAIM, OLD, subject="tl-1", backlog="tasks", tracker_root="/tracker")
    result = reconcile_claims(ports(con, repo, lambda _action: False))
    assert result.conclusion is Conclusion.UNAVAILABLE and "claims" in result.detail
    assert gate.pending()[0].state is ActionState.UNCERTAIN
    con.close()
    con = connect(path)
    try:
        recovering = replace(ports(con, repo, lambda _action: True), observe=lambda _owner: Seen.GONE)
        assert reconcile_claims(recovering).conclusion is Conclusion.COMPLETE
        assert not recovering.store.pending()
    finally:
        con.close()


@pytest.mark.parametrize("seen", [Seen.ALIVE, Seen.UNKNOWN])
@pytest.mark.parametrize("uncertain", [False, True])
def test_live_or_unknown_admission_owner_is_never_adopted(
    factory: sqlite3.Connection, repo: FakeRepo, seen: Seen, uncertain: bool,
) -> None:
    recovering = ports(factory, repo, lambda _action: pytest.fail("must preserve the claim"))
    action = recovering.store.authorize(ActionKind.CLAIM, OLD, subject="tl-1", backlog="tasks", tracker_root="/tracker")
    assert action is not None
    if uncertain:
        recovering.store.uncertain(action)
    before = recovering.store.pending()
    result = reconcile_claims(replace(recovering, observe=lambda _owner: seen))
    assert result.conclusion is (Conclusion.UNAVAILABLE if uncertain or seen is Seen.UNKNOWN else Conclusion.WAITING)
    assert recovering.store.pending() == before


def test_committed_attempt_adopts_its_claim_and_other_action_kinds_are_untouched(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path,
) -> None:
    slots(factory, repo, root, 1)
    assert isinstance(admission(factory, tmp_path, Tracker(factory, tmp_path / "artifacts"), repo).admit(request(tmp_path, repo)), Admitted)
    recovering = ports(factory, repo, lambda _action: pytest.fail("an attempt still owns this claim"))
    assert recovering.store.authorize(ActionKind.CLAIM, OLD, subject="tl-1", backlog="tasks", tracker_root="/tracker")
    other = recovering.store.authorize(ActionKind.DISPATCH, OLD, subject="other")
    assert other is not None
    assert reconcile_claims(recovering).conclusion is Conclusion.COMPLETE
    assert recovering.store.pending() == (other,)
    assert len(AttemptStore(lambda: factory).attempts("tasks", "tl-1")) == 1
