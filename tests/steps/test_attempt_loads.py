"""Concrete attempt loads preserve optional results, identity fences and historical evidence."""

import sqlite3

import pytest
from test_attempt_store import FIRST, KEY, seed

from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_store import AttemptLoads, AttemptStore, retained_on
from taskloop.attempt_types import AttemptKey, Committed, FileRef, Rejected
from taskloop.step import Step


@pytest.fixture
def con(factory: sqlite3.Connection) -> sqlite3.Connection:
    seed(factory)
    assert AttemptStore(lambda: factory).register_entry(KEY, FIRST, 10) == "accepted"
    return factory


def test_record_load_preserves_optional_fields_and_slot_base(con: sqlite3.Connection) -> None:
    loads = AttemptLoads(lambda: con)
    record = loads.load(KEY)
    assert record is not None
    assert record.admission.key == KEY and record.admission.entry == FIRST
    assert record.admission.slot_path == "/slots/repo/slot"
    assert record.admission.input_ref == FileRef("input.txt", "0")
    assert record.admission.deadline == 100
    assert record.worker is None and record.session_ref is None and not record.session_conflict
    assert record.base_commit is None and record.end_commit is None and record.start is None
    assert loads.slot_base(KEY) == "d" * 40
    assert loads.collect(KEY) is None and loads.callback(KEY) is None and loads.retained(KEY) is None


@pytest.mark.parametrize("key", [AttemptKey("missing", "dispatch", 1), AttemptKey("attempt", "wrong", 1),
                                 AttemptKey("attempt", "dispatch", 2)])
def test_missing_or_stale_identity_has_no_load_results(con: sqlite3.Connection, key: AttemptKey) -> None:
    loads = AttemptLoads(lambda: con)
    assert loads.load(key) is None and loads.collect(key) is None and loads.callback(key) is None
    assert loads.retained(key) is None and loads.earlier_for(key) is None
    with pytest.raises(StoreRefused, match="absent"):
        loads.slot_base(key)


def test_live_load_refuses_unregistered_entry_and_lost_reservation(con: sqlite3.Connection) -> None:
    loads = AttemptLoads(lambda: con)
    con.execute("UPDATE attempt SET entry_pid=NULL")
    with pytest.raises(StoreRefused, match="unregistered_entry"):
        loads.load(KEY)
    con.execute("UPDATE attempt SET entry_pid=?", (FIRST[0],))
    con.execute("DELETE FROM reservation")
    with pytest.raises(StoreRefused, match="stale_reservation"):
        loads.load(KEY)


def test_malformed_deadline_is_unavailable(con: sqlite3.Connection) -> None:
    con.execute("UPDATE attempt SET deadline='invalid'")
    with pytest.raises(StoreUnavailable, match="Malformed deadline"):
        AttemptLoads(lambda: con).load(KEY)


def test_retained_inputs_and_earlier_evidence_survive_release_on_callers_connection(con: sqlite3.Connection) -> None:
    loads = AttemptLoads(lambda: con)
    con.execute("UPDATE attempt SET step='implement',phase='captured',base_commit=?,end_commit=?,after_commit=?",
                ("b" * 40, "e" * 40, "a" * 40))
    con.execute("DELETE FROM reservation")
    con.execute("INSERT INTO slot_release VALUES ('attempt','dispatch',1,?,10,'kept')", ("d" * 40,))
    retained = loads.retained(KEY)
    assert retained is not None and retained.key == KEY and retained.checked == "e" * 40
    assert retained.input_ref == FileRef("input.txt", "0") and retained.setting.model == "chosen"
    earlier = loads.earlier("repo", "tasks", "tl-1", "/tracker")
    assert earlier is not None and earlier.key == KEY and earlier.end_commit == retained.checked
    assert earlier.step is Step.IMPLEMENT
    assert con.execute("SELECT step FROM attempt WHERE attempt_id=?", (KEY.attempt_id,)).fetchone() == ("implement",)
    assert loads.earlier("other-repo", "tasks", "tl-1", "/tracker") is None
    assert loads.earlier("repo", "other-tasks", "tl-1", "/tracker") is None
    assert loads.earlier("repo", "tasks", "other-task", "/tracker") is None
    assert loads.earlier("repo", "tasks", "tl-1", "/other-tracker") is None
    assert loads.earlier_for(KEY) == earlier
    with pytest.raises(StoreRefused, match="stale_reservation"):
        loads.load(KEY)
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("UPDATE attempt SET model='inside-transaction'")
        inside = retained_on(con, KEY)
        assert inside is not None and inside.setting.model == "inside-transaction"
        assert con.in_transaction
    finally:
        con.rollback()
    assert loads.retained(KEY) == retained


def test_latest_plan_never_falls_back_to_an_older_success(con: sqlite3.Connection) -> None:
    loads = AttemptLoads(lambda: con)
    scope = ("repo", "tasks", "tl-1", "/tracker")
    assert loads.latest_plan(*scope) is None
    con.execute("UPDATE attempt SET phase='captured',base_commit=?,end_commit=?", ("b" * 40, "e" * 40))
    con.execute("INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,t_in,t_cached,t_out,turns,"
                "stdout_path,stdout_digest,stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,"
                "session_state) VALUES ('attempt','dispatch',1,0,0,1,1,8,NULL,3,2,'out','1','err','2','answer','3','diag','4','complete')")
    execution = loads.collect(KEY)
    assert execution is not None and execution.facts.tokens == (8, None, 3) and execution.facts.turns == 2
    assert execution.facts.cumulative is None and execution.answer.kind == "validation_pending"
    assert execution.verdict is None and loads.callback(KEY) is None
    con.execute("INSERT INTO factory_commit (attempt_id,dispatch_token,generation,verdict,blob,observed_at) "
                "VALUES ('attempt','dispatch',1,'committed','artifact',10)")
    plan = loads.latest_plan(*scope)
    assert plan is not None and plan.key == KEY and plan.end_commit == "e" * 40 and plan.blob == "artifact"
    assert plan.revision == 1
    collected = loads.collect(KEY)
    assert collected is not None and collected.verdict == Committed("artifact")
    con.execute("UPDATE factory_commit SET verdict='rejected',reason='paths',blob=NULL")
    collected = loads.collect(KEY)
    assert collected is not None and collected.verdict == Rejected("paths") and loads.latest_plan(*scope) is None
    con.execute("UPDATE factory_commit SET verdict='committed',reason=NULL,blob='artifact'")
    assert loads.latest_plan(*scope) == plan
    # Copy only admission fields: a newer implementation must not hide the latest plan.
    con.execute("INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,"
                "input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,after_commit,"
                "engine_digest,workflow_digest,workflow_sha,admitted_at) "
                "SELECT 'later','later-token',2,'implement',adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,"
                "schema_version,model,effort,access_policy,deadline,number,2,slot_head,end_commit,"
                "engine_digest,workflow_digest,workflow_sha,admitted_at FROM attempt WHERE attempt_id='attempt'")
    assert loads.latest_plan(*scope) == plan
    earlier = loads.earlier_for(KEY)
    assert earlier is not None and earlier.key == AttemptKey("later", "later-token", 2)
    con.execute("UPDATE attempt SET step='plan',after_commit=NULL WHERE attempt_id='later'")
    assert loads.latest_plan(*scope) is None
    for other in (("other", "tasks", "tl-1", "/tracker"), ("repo", "other", "tl-1", "/tracker"),
                  ("repo", "tasks", "other", "/tracker"), ("repo", "tasks", "tl-1", "/other")):
        assert loads.latest_plan(*other) is None and loads.earlier(*other) is None
