"""The dashboard read model for restarts, repeats and factory commit rows: the board and task detail over the same factory.db reads."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import DONE
from dash_read_support import KEY, Tracker, board_of, reads_of
from doubles import REQUIRED, TARGET, D

from taskloop import check_store
from taskloop.attempt_types import AttemptKey
from taskloop.dash_model import AttemptBody, FeedPage, TaskDetail
from taskloop.dash_task import TaskPorts, build_body, build_feed, build_task, history
from taskloop.evidence_files import EvidenceFiles
from taskloop.step import decode_step


@pytest.mark.parametrize("outcome,reason", [("passed", None), ("failed", "test:failed")])
def test_checks_rerun_after_restart_keeps_its_number_and_prior_attempt_regardless_of_outcome(
    checking: sqlite3.Connection,
    tmp_path: Path,
    outcome: str,
    reason: str | None,
) -> None:
    checking.execute(
        "UPDATE checks_attempt SET phase='concluded',conclusion=?,reason=?,concluded_at=5,released_at=6,parked=? WHERE attempt_id='checks'",
        (outcome, reason, D),
    )
    checking.execute("DELETE FROM reservation WHERE attempt_id='checks'")
    again = check_store.ChecksAdmitted(AttemptKey("again", "again-token", 1), "implement", 2, "s2", D, TARGET, REQUIRED, 100.0)
    check_store.insert(checking, again)
    found = build_task(TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(each.step, each.n, each.after, each.repeat_of) for each in found.attempts[1:]] == [
        ("checks", 1, None, None),
        ("checks", 2, "repeat", 1),
    ]
    assert found.attempts[1].summary == (reason or outcome)
    assert (found.attempts[2].reason, found.attempts[2].state, found.attempts[2].summary) == ("The factory restarted", "running", "running")


def test_first_checks_for_another_implement_attempt_are_not_a_restart(checking: sqlite3.Connection, tmp_path: Path) -> None:
    checking.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,previous_attempt_id,repeat_reason,
        phase,base_commit,end_commit,after_commit,engine_digest,workflow_digest,workflow_sha,admitted_at)
        SELECT 'another','another-token',1,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
        schema_version,model,effort,access_policy,deadline,2,3,slot_head,'implement','unsafe',phase,base_commit,end_commit,NULL,
        engine_digest,workflow_digest,workflow_sha,admitted_at
        FROM attempt WHERE attempt_id='implement'"""
    )
    checking.execute("INSERT INTO slot_release VALUES ('another','another-token',1,?,7,'kept')", (D,))
    check_store.insert(
        checking, check_store.ChecksAdmitted(AttemptKey("fresh", "fresh-token", 1), "another", 1, "s2", D, TARGET, REQUIRED, 100.0)
    )
    check_store.insert(
        checking, check_store.ChecksAdmitted(AttemptKey("again", "again-token", 1), "another", 2, "s2", D, TARGET, REQUIRED, 100.0)
    )
    found = build_task(TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    checks = [each for each in found.attempts if each.step == "checks"]
    assert [(each.n, each.after, each.repeat_of, each.reason) for each in checks] == [
        (1, None, None, None),
        (2, None, None, None),
        (3, "repeat", 2, "The factory restarted"),
    ]


def restarted_at_plan(con: sqlite3.Connection) -> None:
    """tl-1's plan attempt `attempt` (seq 1) is followed by an implement attempt and a second plan attempt, each with stored
    number 1, the way a restart at plan starts a new chain."""
    for attempt, step, seq in (("implement", "implement", 2), ("again", "plan", 3)):
        con.execute(
            """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
            input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,after_commit,
            engine_digest,workflow_digest,workflow_sha,admitted_at)
            SELECT ?,?,1,?,adapter,backlog,
            task_id,tracker_root,repo_id,slot,input_path,input_digest,schema_version,model,effort,access_policy,deadline,1,?,
            slot_head,?,engine_digest,workflow_digest,workflow_sha,admitted_at
            FROM attempt WHERE attempt_id='attempt'""",
            (attempt, f"{attempt}-token", step, seq, "a" * 40 if step == "implement" else None),
        )


def test_a_plan_restarted_at_plan_is_its_own_try_that_can_be_read_by_its_number(
    registered: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    restarted_at_plan(registered)
    files = EvidenceFiles(tmp_path)
    ports = TaskPorts(reads_of(registered), files, Tracker())
    found = build_task(ports, "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(each.step, each.n, each.after) for each in found.attempts] == [
        ("plan", 1, None),
        ("implement", 1, None),
        ("plan", 2, "restart_at_plan"),
    ]
    assert found.task.attempt == 2 and found.task.repeat is not None and found.task.repeat.kind == "restart_at_plan"
    assert found.task.repeat.reason == "Reason not recorded"
    rows = tuple(replace(row, step=decode_step(row.step)) for row in ports.reads.store.attempts("tasks", "tl-1"))
    assert history(ports, rows) == found.attempts
    (board_task,) = board_of(registered, files, Tracker()).tasks
    assert board_task.attempt == 2 and board_task.repeat is not None
    assert (board_task.repeat.kind, board_task.repeat.reason) == ("restart_at_plan", "Reason not recorded")
    files.put_input(KEY, "Plan the actual task")
    ref = files.put_input(AttemptKey("again", "again-token", 1), "Plan it again after the owner's edit")
    registered.execute("UPDATE attempt SET input_path=?,input_digest=? WHERE attempt_id='again'", (ref.path, ref.digest))
    first, second = (build_body(ports, "tasks", "tl-1", "plan", each) for each in (1, 2))
    assert isinstance(first, AttemptBody) and isinstance(second, AttemptBody)
    assert first.input == "Plan the actual task" and second.input == "Plan it again after the owner's edit"
    assert isinstance(build_feed(ports, "tasks", "tl-1", "plan", 2, None), FeedPage)
    assert build_feed(ports, "tasks", "tl-1", "plan", 3, None) is None


def unsafe_repeat(con: sqlite3.Connection, listing: str = '["src/link.py", "src/stray.py"]') -> None:
    """`checking`'s implement attempt answered `implemented` (a valid, committing answer) and its factory commit was unfinished: it was
    repeated as try 2 for `unsafe`, which stored what the factory commit listed."""
    con.execute(DONE[0])
    con.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,previous_attempt_id,repeat_reason,
        repeat_listing,engine_digest,workflow_digest,workflow_sha,
        admitted_at) SELECT 'again','again-token',2,step,adapter,backlog,task_id,tracker_root,
        repo_id,slot,input_path,input_digest,
        schema_version,model,effort,access_policy,deadline,2,3,slot_head,'implement','unsafe',
        ?,engine_digest,workflow_digest,workflow_sha,admitted_at FROM attempt WHERE attempt_id='implement'""",
        (listing,),
    )


def test_an_unsettled_factory_commit_is_its_own_row_that_names_the_failed_check_and_what_it_listed(
    checking: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    unsafe_repeat(checking)
    ports = TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker())
    found = build_task(ports, "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(each.step, each.n) for each in found.attempts] == [("implement", 1), ("commit", 1), ("checks", 1), ("implement", 2)]
    committing, repeat = found.attempts[1], found.attempts[3]
    assert (committing.state, committing.summary) == ("failed", "uncommitted:unsafe")
    assert (repeat.after, repeat.reason, repeat.repeat_of, repeat.led_by) == ("repeat", "unsafe", 1, 1)
    body = build_body(ports, "tasks", "tl-1", "commit", 1)
    assert isinstance(body, AttemptBody) and body.input is None and body.result.factory_commit is not None
    shown = body.result.factory_commit
    assert (shown.of_step, shown.of, shown.result, shown.listing) == ("implement", 1, "uncommitted:unsafe", ("src/link.py", "src/stray.py"))
    assert [each.state for each in shown.checks] == ["passed", "failed", "not_run", "not_run", "not_run"]


def test_a_stored_verdict_is_a_factory_commit_row_that_passed_or_broke_a_rule(checking: sqlite3.Connection, tmp_path: Path) -> None:
    checking.execute(DONE[0])
    checking.execute(DONE[1])
    ports = TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker())
    body = build_body(ports, "tasks", "tl-1", "commit", 1)
    assert isinstance(body, AttemptBody) and body.result.factory_commit is not None
    assert body.result.factory_commit.result == "committed" and {each.state for each in body.result.factory_commit.checks} == {"passed"}
    checking.execute("DELETE FROM factory_commit")
    checking.execute(
        "INSERT INTO factory_commit (attempt_id,dispatch_token,generation,verdict,reason,observed_at) "
        "VALUES ('implement','implement-token',1,'rejected','paths',5)"
    )
    broken = build_body(ports, "tasks", "tl-1", "commit", 1)
    assert isinstance(broken, AttemptBody) and broken.result.factory_commit is not None
    assert broken.result.factory_commit.result == "rejected:paths"
    assert [each.state for each in broken.result.factory_commit.checks] == ["passed"] * 4 + ["failed"]


def test_an_attempt_that_never_reached_factory_commit_has_no_factory_commit_row(checking: sqlite3.Connection, tmp_path: Path) -> None:
    found = build_task(TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail) and [each.step for each in found.attempts] == ["implement", "checks"]
    assert build_body(TaskPorts(reads_of(checking), EvidenceFiles(tmp_path), Tracker()), "tasks", "tl-1", "commit", 1) is None


def test_a_repeats_prompt_marks_the_lines_it_added_to_the_prompt_it_repeats(checking: sqlite3.Connection, tmp_path: Path) -> None:
    unsafe_repeat(checking)
    files = EvidenceFiles(tmp_path)
    for key, text in (
        (AttemptKey("implement", "implement-token", 1), "Title\n\nDo the thing.\n"),
        (AttemptKey("again", "again-token", 2), "A path cannot be committed.\nsrc/link.py\n\nTitle\n\nDo the thing.\n"),
    ):
        ref = files.put_input(key, text)
        checking.execute("UPDATE attempt SET input_path=?,input_digest=? WHERE attempt_id=?", (ref.path, ref.digest, key.attempt_id))
    ports = TaskPorts(reads_of(checking), files, Tracker())
    first, second = (build_body(ports, "tasks", "tl-1", "implement", each) for each in (1, 2))
    assert isinstance(first, AttemptBody) and isinstance(second, AttemptBody)
    assert first.added == () and second.added == ((0, 3),)


def test_a_plan_repeat_is_a_repeat_on_the_board_and_in_history(registered: sqlite3.Connection, tmp_path: Path) -> None:
    registered.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,previous_attempt_id,
        repeat_reason,engine_digest,workflow_digest,workflow_sha,admitted_at)
        SELECT 'again','again-token',2,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
        schema_version,model,effort,access_policy,deadline,2,2,slot_head,'attempt','unsafe',engine_digest,workflow_digest,workflow_sha,
        admitted_at FROM attempt WHERE attempt_id='attempt'"""
    )
    files = EvidenceFiles(tmp_path)
    (board_task,) = board_of(registered, files, Tracker()).tasks
    assert board_task.repeat is not None
    assert (board_task.repeat.kind, board_task.repeat.reason) == ("repeat", "unsafe")
    found = build_task(TaskPorts(reads_of(registered), files, Tracker()), "tasks", "tl-1")
    assert isinstance(found, TaskDetail)
    assert [(a.step, a.n, a.after) for a in found.attempts] == [("plan", 1, None), ("plan", 2, "repeat")]
    assert (found.attempts[-1].reason, found.attempts[-1].repeat_of) == ("unsafe", 1)
