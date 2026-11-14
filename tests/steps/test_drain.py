"""Drain boundaries over real SQLite and deterministic, boot-aware process observations; no process is started."""

import sqlite3
from collections.abc import Generator
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import FixedIds, PinnedViews
from git_porcelain.testing import FakeRepo
from sqlite_store import Store
from test_admit import tasks
from test_round import held, seed

from taskloop.attempt_store import AttemptStore
from taskloop.drain.composition import open_drain
from taskloop.drain.drain import Ports, drain, inspect
from taskloop.drain.models import Action, ActionKind, Boundary, Conclusion, Identity, Result, Role, Seen, State
from taskloop.drain.reconcile import Reconcile
from taskloop.drain.restart import restart
from taskloop.drain.store import DrainStore
from taskloop.factory_schema import SCHEMA
from taskloop.ids import NativeIds
from taskloop.land_store import LandStore

CALLER = Identity(pid=100, pgid=100, start="caller", boot="boot")


@pytest.fixture
def database(tmp_path: Path) -> Generator[tuple[Path, sqlite3.Connection]]:
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    yield path, con
    con.close()


def opened(path: Path) -> Generator[Ports]:
    with open_drain(path) as ports:
        assert isinstance(ports, Ports)
        yield ports


def test_idle_includes_held_and_reserved_unlaunched_work(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    seed(con, "tl-1", "one")
    seed(con, "tl-2", "two")
    con.execute("UPDATE attempt SET backlog='other',session_ref='keep-session' WHERE attempt_id='two'")
    held(con, "one")
    con.execute("INSERT INTO reservation VALUES('s1','repo',1,'two')")
    before = {table: con.execute(f"SELECT * FROM {table}").fetchall() for table in ("attempt", "reservation", "task_hold")}
    for ports in opened(path):
        assert drain(ports).conclusion is Conclusion.COMPLETE
        assert ports.store.boundary().state is State.COMPLETE
        assert drain(ports).generation == 1  # another caller joins, including an already completed boundary
    assert {table: con.execute(f"SELECT * FROM {table}").fetchall() for table in before} == before


def executions(con: sqlite3.Connection) -> None:
    seed(con, "tl-1", "agent", phase="captured", entry=(11, "entry-agent", "boot"))
    con.execute("UPDATE attempt SET worker_pid=12,worker_pgid=12,worker_start='agent',worker_boot='boot' WHERE attempt_id='agent'")
    seed(con, "tl-2", "implement", phase="captured")
    con.execute("UPDATE attempt SET backlog='other' WHERE attempt_id='implement'")
    con.execute(
        "INSERT INTO setup_run(attempt_id,run,dispatch_token,generation,commit_sha,digest,pid,pgid,proc_start,boot,started_at) "
        "VALUES('agent',1,'token-agent',1,?,?,13,13,'setup','boot',1)",
        ("a" * 40, "d" * 64),
    )
    con.execute(
        "INSERT INTO checks_attempt(attempt_id,dispatch_token,generation,after_attempt_id,number,slot,slot_head,"
        "target_commit,required,deadline,entry_pid,entry_start,entry_boot,phase,conclusion,concluded_at) "
        "VALUES('checks','token-checks',1,'implement',1,'s2',?,?,'[]',100,14,'entry-checks','boot','concluded','passed',2)",
        ("a" * 40, "b" * 40),
    )
    con.execute(
        "INSERT INTO check_result(attempt_id,dispatch_token,generation,block,position,name,argv_digest,timeout,pid,pgid,proc_start,boot,"
        "started_at,"
        "ended_at,rc,conclusion) VALUES('checks','token-checks',1,1,1,'test',?,30,15,15,'checks','boot',1,2,0,'passed')",
        ("e" * 64,),
    )


def test_entries_agents_setup_and_checks_finish_naturally_across_backlogs(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    executions(con)
    live = {11, 12, 13, 14, 15}
    reports: list[Result] = []
    finishing = [{12, 13}, {15}, {11}, {14}]

    def wait(_seconds: float) -> None:
        assert DrainStore(lambda: con, ids=NativeIds()).boundary().state is State.DRAINING
        live.difference_update(finishing.pop(0))

    for ports in opened(path):
        watching = replace(
            ports, observe=lambda owner: Seen.ALIVE if owner.identity.pid in live else Seen.GONE, wait=wait, report=reports.append
        )
        found = drain(watching)
        assert found.conclusion is Conclusion.COMPLETE and not finishing
    assert [{owner.role for owner in result.active} for result in reports[1:]] == [
        {Role.ENTRY, Role.AGENT, Role.SETUP, Role.CHECK},
        {Role.ENTRY, Role.CHECK},
        {Role.ENTRY},
        {Role.ENTRY},
    ]
    assert con.execute("SELECT count(*) FROM attempt").fetchone() == (2,)
    assert con.execute("SELECT phase,conclusion FROM checks_attempt").fetchone() == ("concluded", "passed")


def test_a_historical_entry_and_child_block_even_with_a_newer_attempt(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    seed(con, "tl-1", "old", phase="captured", entry=(20, "old-entry", "boot"))
    con.execute("UPDATE attempt SET worker_pid=21,worker_pgid=21,worker_start='old-agent',worker_boot='boot' WHERE attempt_id='old'")
    seed(con, "tl-2", "new")
    con.execute("UPDATE attempt SET task_id='tl-1',seq=2 WHERE attempt_id='new'")
    for ports in opened(path):
        generation = ports.store.request().generation
        observed = inspect(replace(ports, observe=lambda owner: Seen.ALIVE if owner.identity.pid == 21 else Seen.GONE), generation)
        assert observed.conclusion is Conclusion.WAITING
        assert [(owner.subject, owner.role) for owner in observed.active] == [("old", Role.AGENT)]
        observed = inspect(replace(ports, observe=lambda owner: Seen.ALIVE if owner.identity.pid == 20 else Seen.GONE), generation)
        assert observed.conclusion is Conclusion.WAITING  # a stored result does not prove its entry has stopped


def test_unknown_identity_never_completes_or_removes_the_fence(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    seed(con, "tl-1", "one", entry=(22, "entry", "boot"))
    for ports in opened(path):
        found = drain(replace(ports, observe=lambda _owner: Seen.UNKNOWN))
        assert found.conclusion is Conclusion.UNAVAILABLE and len(found.uncertain) == 1
        assert ports.store.boundary().state is State.DRAINING


def test_interrupted_wait_resumes_with_fresh_connections_and_joins_the_same_request(tmp_path: Path) -> None:
    path = tmp_path / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    seed(con, "tl-1", "one", entry=(23, "entry", "boot"))
    con.execute("UPDATE attempt SET session_ref='unfinished-session'")
    con.execute("INSERT INTO reservation VALUES('s1','repo',1,'one')")
    con.close()

    def interrupted(_seconds: float) -> None:
        raise KeyboardInterrupt

    for ports in opened(path):
        found = drain(replace(ports, observe=lambda _owner: Seen.ALIVE, wait=interrupted))
        assert found.conclusion is Conclusion.INTERRUPTED and found.generation == 1
    for ports in opened(path):
        assert ports.store.request().generation == 1
        found = drain(replace(ports, observe=lambda _owner: Seen.GONE))
        assert found.conclusion is Conclusion.COMPLETE and found.generation == 1
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT session_ref FROM attempt").fetchall() == [("unfinished-session",)]
        assert con.execute("SELECT * FROM reservation").fetchall() == [("s1", "repo", 1, "one")]


def test_dispatch_authorized_before_the_fence_stays_visible_until_registration_finishes(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    store = DrainStore(lambda: con, ids=NativeIds())
    action = store.authorize(ActionKind.DISPATCH, CALLER, subject="one")
    assert action is not None
    for ports in opened(path):
        boundary = store.request()
        assert ports.store.request() == boundary  # another caller does not replace the request
        found = inspect(replace(ports, observe=lambda _owner: Seen.ALIVE), boundary.generation)
        assert len(found.actions) == 1 and found.conclusion is Conclusion.WAITING
        assert not store.complete(boundary.generation)
        seed(con, "tl-1", "one", entry=(24, "late-registration", "boot"))
        store.finish(action)
        found = inspect(replace(ports, observe=lambda _owner: Seen.ALIVE), boundary.generation)
        assert found.conclusion is Conclusion.WAITING and len(found.active) == 1
        assert drain(replace(ports, observe=lambda _owner: Seen.GONE)).conclusion is Conclusion.COMPLETE
    assert store.authorize(ActionKind.DISPATCH, CALLER, subject="two") is None


def test_unresolved_external_action_is_uncertain_after_its_owner_dies(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    action = DrainStore(lambda: con, ids=NativeIds()).authorize(ActionKind.FINALIZE, CALLER, subject="tl-1")
    assert action is not None
    for ports in opened(path):
        found = drain(replace(ports, observe=lambda _owner: Seen.GONE))
        assert found.conclusion is Conclusion.UNAVAILABLE and len(found.actions) == 1
        assert found.actions[0].action_id == action.action_id
        assert ports.store.boundary().state is State.DRAINING


def test_restart_finishes_incomplete_drain_then_only_a_later_invocation_reopens(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    store = DrainStore(lambda: con, ids=NativeIds())
    store.request()
    for ports in opened(path):
        finished = restart(ports)
        assert isinstance(finished, Result) and finished.conclusion is Conclusion.COMPLETE
        assert store.boundary().state is State.COMPLETE
    for ports in opened(path):
        begun = restart(ports)
        assert isinstance(begun, Boundary) and begun.state is State.OPEN and begun.generation == 2
    assert store.authorize(ActionKind.ROUND, CALLER, generation=0) is None  # an old scheduler cannot resume
    assert store.authorize(ActionKind.ROUND, CALLER, generation=2) is not None
    boundary = store.request()
    assert boundary.generation == 3 and store.reopen(Boundary(state=State.COMPLETE, generation=1)) is None


def test_reopen_rechecks_liveness_and_refuses_unknown_owners(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    seed(con, "tl-1", "one", entry=(25, "entry", "boot"))
    for ports in opened(path):
        assert drain(replace(ports, observe=lambda _owner: Seen.GONE)).conclusion is Conclusion.COMPLETE
        result = restart(replace(ports, observe=lambda _owner: Seen.UNKNOWN))
        assert isinstance(result, Result) and result.conclusion is Conclusion.UNAVAILABLE
        assert ports.store.boundary().state is State.COMPLETE


def test_malformed_partial_identity_is_uncertain(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    seed(con, "tl-1", "one", entry=(26, "entry", "boot"))
    con.execute("UPDATE attempt SET entry_boot=NULL")
    for ports in opened(path):
        assert drain(ports).conclusion is Conclusion.UNAVAILABLE
        assert ports.store.boundary().state is State.DRAINING


def test_reconciliation_has_one_durable_owner_before_external_io(database: tuple[Path, sqlite3.Connection]) -> None:
    path, con = database
    store = DrainStore(lambda: con, ids=NativeIds())
    original = store.authorize(ActionKind.DISPATCH, CALLER, subject="one")
    assert original is not None
    reconciler = Identity(pid=101, pgid=101, start="reconciler", boot="boot")
    nested: list[Result] = []
    for ports in opened(path):
        watching = replace(ports, observe=lambda owner: Seen.GONE if owner.identity == CALLER else Seen.ALIVE, me=lambda: reconciler)

        def reconcile(_action: Action, watching: Ports = watching) -> bool:
            nested.append(inspect(watching, 1))
            assert not store.complete(1)
            assert store.adopt(original, CALLER) is None  # the original revision cannot steal it back
            return True

        result = drain(replace(watching, reconcile=reconcile))
        assert result.conclusion is Conclusion.COMPLETE
        assert len(nested) == 1 and nested[0].conclusion is Conclusion.WAITING
        assert nested[0].actions[0].owner == reconciler


@pytest.mark.parametrize("committed", [False, True])
def test_dead_claim_intent_is_returned_or_adopted_from_the_committed_attempt(
    database: tuple[Path, sqlite3.Connection],
    repo: FakeRepo,
    committed: bool,
) -> None:
    path, con = database
    if committed:
        seed(con, "tl-1", "one")
    store = DrainStore(lambda: con, ids=NativeIds())
    action = store.authorize(ActionKind.CLAIM, CALLER, subject="tl-1", backlog="tasks", tracker_root="/tracker")
    assert action is not None
    returned: list[str] = []

    def return_claim(action: Action) -> bool:
        assert not con.in_transaction
        assert store.pending()[0].owner == action.owner  # the reconciler owns the intent before external IO
        returned.append(action.subject)
        return True

    reconcile = Reconcile(AttemptStore(lambda: con), LandStore(lambda: con), PinnedViews(repo), tasks, return_claim, lambda: 20)
    for ports in opened(path):
        result = drain(replace(ports, observe=lambda _owner: Seen.GONE, reconcile=reconcile))
        assert result.conclusion is Conclusion.COMPLETE and not store.pending()
    assert returned == ([] if committed else ["tl-1"])
    assert con.execute("SELECT count(*) FROM attempt").fetchone() == (int(committed),)


def test_drain_authorization_and_reconciliation_keep_the_supplied_action_id(database: tuple[Path, sqlite3.Connection]) -> None:
    _, con = database
    ids = FixedIds()
    store = DrainStore(lambda: con, ids=ids)
    action = store.authorize(ActionKind.DISPATCH, CALLER, subject="attempt")
    assert action is not None and action.action_id == ids.fresh[0]
    next_owner = Identity(pid=101, pgid=101, start="reconciler", boot="boot")
    adopted = store.adopt(action, next_owner)
    assert adopted is not None and adopted.action_id == action.action_id and len(ids.fresh) == 1
    assert store.pending() == (adopted,)
    store.finish(adopted)
    assert not store.pending()
