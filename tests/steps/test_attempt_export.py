"""The A/A and A/B export and the slot list: typed reads of a real factory.db that keep unknown values unknown."""

import sqlite3
from dataclasses import fields

from doubles import ENGINE, PIN_DIGEST
from hold_fixtures import event

from taskloop import attempt_export, rows_render, slot_list
from taskloop.attempt_export_store import ExportRow, ExportStore
from taskloop.slot_list_store import SlotHold, SlotListStore
from taskloop.task_event_codec import encode

COLUMNS = [
    "task_id",
    "step",
    "number",
    "repeat_reason",
    "engine_digest",
    "workflow_digest",
    "workflow_sha",
    "harness",
    "model",
    "effort",
    "compaction_token_limit",
    "input_digest",
    "admitted_at",
    "ended_at",
    "wall_seconds",
    "disposition",
    "effect",
    "answer_kind",
    "rc",
    "timed_out",
    "turns",
    "t_in",
    "t_cached",
    "t_out",
    "c_in",
    "c_cached",
    "c_out",
    "usage_incomplete",
    "latest_checks_conclusion",
    "latest_checks_reason",
    "ran_model",
    "ran_effort",
    "harness_version",
    "ran_model_differs",
    "max_attempts",
    "attempt_id",
    "backlog",
    "previous_attempt_id",
    "seq",
    "base_commit",
    "factory_commit_verdict",
    "chain_id",
    "setup_seconds",
    "check_seconds",
    "rework_count",
    "repair_count",
    "time_to_green_seconds",
    "task_total_seconds",
    "failed_checks",
    "hold_cause",
    "hold_text",
    "terminal_result",
    "changed_files",
    "changed_lines",
    "launched_input_digest",
    "t_reasoning",
]


def test_the_export_gives_one_row_per_attempt_with_its_identity_and_no_invented_numbers(registered: sqlite3.Connection) -> None:
    found = attempt_export.export(ExportStore(lambda: registered), None)
    assert isinstance(found, attempt_export.AttemptExport)
    (row,) = found.rows
    assert [each.name for each in fields(ExportRow)] == COLUMNS
    assert (row.task_id, row.step, row.number) == ("tl-1", "plan", 1)
    assert (row.engine_digest, row.workflow_digest) == (ENGINE, PIN_DIGEST)
    assert row.ended_at is None and row.wall_seconds is None and row.t_in is None  # not captured: unknown, not zero
    assert (row.attempt_id, row.backlog, row.chain_id, row.previous_attempt_id, row.seq) == ("attempt", "tasks", "attempt", None, 1)
    assert (row.setup_seconds, row.time_to_green_seconds, row.hold_cause, row.terminal_result) == (None, None, None, None)
    assert row.check_seconds == {} and (row.rework_count, row.repair_count, row.task_total_seconds) == (0, 0, None)
    assert (row.failed_checks, row.hold_text) == ([], None)
    header, line = rows_render.lines(found)
    assert header.split(",") == COLUMNS and line.startswith("tl-1,plan,1,,")


def test_the_export_filters_by_backlog_and_the_wall_time_is_the_recorded_difference(registered: sqlite3.Connection) -> None:
    registered.execute("UPDATE attempt SET phase='captured',base_commit=slot_head,ended_at=admitted_at+2.5")
    store = ExportStore(lambda: registered)
    assert attempt_export.export(store, "other") == attempt_export.AttemptExport(())
    found = attempt_export.export(store, "tasks")
    assert isinstance(found, attempt_export.AttemptExport) and found.rows[0].wall_seconds == 2.5
    assert rows_render.records(found)[0]["usage_incomplete"] is None


def test_the_slot_list_shows_a_held_slot_with_its_attempt_and_a_free_one(registered: sqlite3.Connection) -> None:
    repo = registered.execute("SELECT repo_id FROM slot").fetchone()[0]
    registered.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s2','/slots/s2')", (repo,))
    found = slot_list.list_slots(SlotListStore(lambda: registered))
    assert isinstance(found, slot_list.SlotList)
    assert [(row.name, row.state, row.attempt_id) for row in found.rows] == [("s1", SlotHold.HELD, "attempt"), ("s2", SlotHold.FREE, None)]
    assert rows_render.records(found)[1]["attempt_id"] is None


def test_the_export_flags_a_model_that_differs_from_the_asked_one_and_names_the_workflow_cap(registered: sqlite3.Connection) -> None:
    store = ExportStore(lambda: registered)
    (row,) = store.attempts(None)
    assert (row.ran_model_differs, row.max_attempts) == (None, 3)  # nothing reported: unknown, not "same"
    registered.execute(
        """INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,stdout_digest,stderr_path,
        stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,session_state,model)
        VALUES ('attempt','dispatch',1,0,0,1,1,'o','d','e','d','a','d','g','d','valid','complete','chosen')"""
    )
    assert store.attempts(None)[0].ran_model_differs == 0
    registered.execute("UPDATE execution SET model='resolved-id'")
    assert store.attempts(None)[0].ran_model_differs == 1
    registered.execute("UPDATE workflow_file SET content=?", (b"this is [not a workflow",))
    assert store.attempts(None)[0].max_attempts is None


def test_export_uses_latest_checks_and_setup_without_writing(registered: sqlite3.Connection) -> None:
    registered.execute("UPDATE attempt SET phase='captured',base_commit=slot_head,ended_at=4")
    registered.execute(
        """INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at,ended_at,conclusion)
        SELECT attempt_id,1,dispatch_token,generation,slot_head,engine_digest,1,2,'passed' FROM attempt"""
    )
    registered.execute(
        """INSERT INTO setup_run (attempt_id,run,dispatch_token,generation,commit_sha,digest,started_at,ended_at,conclusion)
        SELECT attempt_id,2,dispatch_token,generation,slot_head,engine_digest,2,3.5,'passed' FROM attempt"""
    )
    for number, conclusion, reason in ((1, "failed", "check:failed"), (2, "passed", None)):
        registered.execute(
            """INSERT INTO checks_attempt
            (attempt_id,dispatch_token,generation,after_attempt_id,number,slot,slot_head,target_commit,required,deadline,
             phase,conclusion,reason,concluded_at)
            SELECT ?,?,1,attempt_id,?,slot,slot_head,slot_head,'[]',100,'concluded',?,?,10 FROM attempt""",
            (f"checks-{number}", f"token-{number}", number, conclusion, reason),
        )
    registered.execute(
        """INSERT INTO check_result
        (attempt_id,block,position,name,dispatch_token,generation,argv_digest,timeout,started_at,ended_at,conclusion)
        VALUES ('checks-1',1,0,'old','token-1',1,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',10,3,4,'failed'),
               ('checks-2',1,0,'check','token-2',1,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',10,3,8,'passed'),
               ('checks-2',2,0,'check','token-2',1,'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',10,8,9,'passed')"""
    )
    before = registered.total_changes
    found = attempt_export.export(ExportStore(lambda: registered), None)
    assert isinstance(found, attempt_export.AttemptExport)
    (row,) = found.rows
    assert (row.wall_seconds, row.setup_seconds, row.time_to_green_seconds) == (3, 1.5, 9)
    assert row.check_seconds == {"check": 1} and row.latest_checks_conclusion == "passed"
    assert registered.total_changes == before
    registered.execute("UPDATE checks_attempt SET conclusion='failed',reason='check:failed' WHERE number=2")
    assert ExportStore(lambda: registered).attempts(None)[0].time_to_green_seconds is None


def _successor(con: sqlite3.Connection, new: str, previous: str, **columns: str) -> None:
    """A copy of the plan attempt as a later attempt of the same task: `columns` are SQL expressions that replace its columns."""
    values = {
        "attempt_id": f"'{new}'",
        "dispatch_token": f"'{new}-token'",
        "previous_attempt_id": f"'{previous}'",
        "seq": "seq+1",
        "admitted_at": "5",
    } | columns
    names = [row[1] for row in con.execute("PRAGMA table_info(attempt)")]
    selected = ",".join(values.get(name, name) for name in names)
    con.execute(f"INSERT INTO attempt ({','.join(names)}) SELECT {selected} FROM attempt WHERE attempt_id='attempt'")


def _checks(con: sqlite3.Connection, after: str, number: int, conclusion: str, names: tuple[tuple[str, str], ...]) -> None:
    con.execute(
        """INSERT INTO checks_attempt (attempt_id,dispatch_token,generation,after_attempt_id,number,slot,slot_head,target_commit,
        required,deadline,phase,conclusion,reason,concluded_at) SELECT ?,?,1,attempt_id,?,slot,slot_head,slot_head,'[]',100,'concluded',?,?,
        30 FROM attempt WHERE attempt_id=?""",
        (f"checks-{after}", f"token-{after}", number, conclusion, None if conclusion == "passed" else "check:failed", after),
    )
    for position, (name, result) in enumerate(names):
        defined = result != "undefined"
        con.execute(
            """INSERT INTO check_result (attempt_id,block,position,name,dispatch_token,generation,argv_digest,timeout,started_at,
            ended_at,conclusion) VALUES (?,1,?,?,?,1,?,?,3,4,?)""",
            (f"checks-{after}", position, name, f"token-{after}", "a" * 64 if defined else None, 10 if defined else None, result),
        )


def test_the_task_total_spans_plan_to_this_rows_passed_checks_and_repairs_are_not_rework(registered: sqlite3.Connection) -> None:
    _successor(registered, "impl", "attempt", step="'implement'", number="1", previous_attempt_id="NULL", after_commit="slot_head")
    repair = {"step": "'implement'", "number": "1", "after_commit": "slot_head", "repair_context": "'{}'", "seq": "3", "admitted_at": "7"}
    _successor(registered, "fix", "impl", **repair)
    _checks(registered, "fix", 1, "passed", (("lint", "passed"), ("tests", "passed")))
    rows = {row.attempt_id: row for row in ExportStore(lambda: registered).attempts(None)}
    assert (rows["fix"].repair_count, rows["fix"].rework_count) == (1, 0)  # one repair, no failed-check repeat
    assert (rows["fix"].task_total_seconds, rows["fix"].time_to_green_seconds) == (29, 25)  # plan admitted at 1, impl chain at 5
    assert rows["impl"].task_total_seconds is None and rows["attempt"].task_total_seconds is None  # no passed checks of its own


def test_the_export_names_the_failed_checks_and_the_hold_text_of_a_row(registered: sqlite3.Connection) -> None:
    _checks(registered, "attempt", 1, "failed", (("lint", "passed"), ("tests", "failed"), ("docs", "undefined"), ("slow", "timed_out")))
    registered.execute("INSERT INTO task_hold (attempt_id,event,held_at) VALUES ('attempt',?,10)", (encode(event(attempt_id="attempt")),))
    found = attempt_export.export(ExportStore(lambda: registered), None)
    assert isinstance(found, attempt_export.AttemptExport)
    (row,) = found.rows
    assert row.failed_checks == ["tests", "docs", "slow"] and row.hold_text == "Owner decision required."
    assert row.hold_cause == "failed:needs_owner"
    assert rows_render.records(found)[0]["failed_checks"] == ["tests", "docs", "slow"]
    assert '"[""tests"", ""docs"", ""slow""]"' in rows_render.lines(found)[1]


def test_the_export_carries_the_launched_input_digest_and_the_committed_diff_size(registered: sqlite3.Connection) -> None:
    store = ExportStore(lambda: registered)
    row = store.attempts(None)[0]
    assert (row.launched_input_digest, row.changed_files, row.changed_lines) == (None, None, None)  # unknown, not zero
    registered.execute("UPDATE attempt SET phase='captured',base_commit=slot_head,ended_at=4,launched_digest=?", ("e" * 64,))
    registered.execute(
        """INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,stdout_digest,stderr_path,
        stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,session_state)
        VALUES ('attempt','dispatch',1,0,0,1,1,'o','d','e','d','a','d','g','d','valid','complete')"""
    )
    registered.execute(
        "INSERT INTO factory_commit (attempt_id,dispatch_token,generation,verdict,observed_at,files_changed,lines_changed) "
        "VALUES ('attempt','dispatch',1,'committed',5,3,42)"
    )
    row = store.attempts(None)[0]
    assert (row.launched_input_digest, row.changed_files, row.changed_lines) == ("e" * 64, 3, 42)
    assert row.base_commit is not None and row.input_digest != row.launched_input_digest


def test_the_export_carries_the_reasoning_tokens_and_leaves_an_unreported_count_unknown(registered: sqlite3.Connection) -> None:
    store = ExportStore(lambda: registered)
    registered.execute("UPDATE attempt SET phase='captured',base_commit=slot_head,ended_at=4")
    registered.execute(
        """INSERT INTO execution (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,t_out,stdout_path,stdout_digest,
        stderr_path,stderr_digest,answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,session_state)
        VALUES ('attempt','dispatch',1,0,0,1,1,900,'o','d','e','d','a','d','g','d','valid','complete')"""
    )
    assert store.attempts(None)[0].t_reasoning is None  # not reported: unknown, never 0
    registered.execute("UPDATE execution SET t_reasoning=400")
    row = store.attempts(None)[0]
    assert (row.t_out, row.t_reasoning) == (900, 400)
