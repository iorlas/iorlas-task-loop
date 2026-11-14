"""Persisted attempt usage, coverage and totals through the public dashboard read model."""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest
from test_dash_read import Tracker, reads_of, restarted_at_plan, unsafe_repeat

from taskloop.answer_failures import AnswerFailureData, AnswerRule, encode
from taskloop.dash_model import TaskDetail, Usage
from taskloop.dash_task import TaskPorts, build_task
from taskloop.evidence_files import EvidenceFiles


def report(
    con: sqlite3.Connection, attempt: str, tokens: tuple[int | None, int | None, int | None], turns: int | None,
    *, incomplete: bool | None = None,
) -> None:
    """Persist a report at the owning execution boundary; cumulative deliberately differs from attempt usage."""
    con.execute(
        """INSERT OR IGNORE INTO execution
        (attempt_id,dispatch_token,generation,rc,timed_out,work,stands,stdout_path,stdout_digest,stderr_path,stderr_digest,
         answer_path,answer_digest,diagnostic_path,diagnostic_digest,answer_kind,session_state,answer_failure)
        SELECT attempt_id,dispatch_token,generation,0,0,1,1,'o','d','e','d','a','d','g','d','missing','complete',?
        FROM attempt WHERE attempt_id=?""",
        (encode(AnswerFailureData(rule=AnswerRule.MISSING, explanation="Answer must not be empty")), attempt))
    con.execute("""UPDATE execution SET t_in=?,t_cached=?,t_out=?,turns=?,usage_incomplete=?,
                c_in=999999,c_cached=999999,c_out=999999 WHERE attempt_id=?""", (*tokens, turns, incomplete, attempt))


def detail(con: sqlite3.Connection, root: Path, task_id: str = "tl-1") -> TaskDetail:
    found = build_task(TaskPorts(reads_of(con), EvidenceFiles(root), Tracker()), "tasks", task_id)
    assert isinstance(found, TaskDetail)
    return found


@pytest.mark.parametrize(("tokens", "turns", "expected"), [
    ((546541, 496768, 2375), 74, Usage(49773, 496768, 2375, 74, 1, 1)),
    ((0, 0, 0), 0, Usage(0, 0, 0, 0, 1, 1)),
    ((20, 5, 3), None, Usage(15, 5, 3, None, 1, 0)),
    ((None, None, None), 2, Usage(None, None, None, 2, 1, 0)),
    ((None, None, None), None, Usage(attempts=1)),
    ((20, None, 3), 1, Usage(None, None, 3, 1, 1, 0)),
    ((None, 5, None), 1, Usage(None, 5, None, 1, 1, 0)),
    ((20, 5, None), 1, Usage(15, 5, None, 1, 1, 0)),
    ((4, 5, 3), 1, Usage(None, None, 3, 1, 1, 0)),
    ((-1, 5, -2), -3, Usage(None, 5, None, None, 1, 0)),
    ((20, -5, 3), 1, Usage(None, None, 3, 1, 1, 0)),
])
def test_attempt_usage_preserves_reported_counts_and_unknowns(
    registered: sqlite3.Connection, tmp_path: Path, tokens: tuple[int | None, int | None, int | None], turns: int | None,
    expected: Usage,
) -> None:
    report(registered, "attempt", tokens, turns)
    found = detail(registered, tmp_path)
    assert found.attempts[0].usage == expected
    assert found.step_usage == {"plan": expected} and found.usage == expected
    encoded = json.loads(json.dumps(asdict(found)))
    assert encoded["attempts"][0]["usage"] == asdict(expected)
    assert encoded["step_usage"]["plan"] == encoded["usage"] == asdict(expected)


def test_no_execution_and_empty_task_have_no_report(registered: sqlite3.Connection, tmp_path: Path) -> None:
    found = detail(registered, tmp_path)
    assert found.attempts[0].usage == Usage(attempts=1)
    assert found.step_usage == {"plan": Usage(attempts=1)} and found.usage == Usage(attempts=1)
    empty = detail(registered, tmp_path, "tl-9")
    assert empty.step_usage == {} and empty.usage == Usage()


def test_step_and_task_totals_include_abandoned_history(registered: sqlite3.Connection, tmp_path: Path) -> None:
    restarted_at_plan(registered)
    registered.execute("INSERT INTO slot_release VALUES ('implement','implement-token',1,?,10,'not_held')", ("a" * 40,))
    report(registered, "attempt", (100, 60, 10), 1)
    report(registered, "implement", (40, 10, 3), 2)
    report(registered, "again", (20, 5, 2), 1)
    found = detail(registered, tmp_path)
    assert [each.past for each in found.attempts] == [True, True, False]
    assert found.step_usage == {"plan": Usage(55, 65, 12, 2, 2, 2), "implement": Usage(30, 10, 3, 2, 1, 1)}
    assert found.usage == Usage(85, 75, 15, 4, 3, 3)


def test_retries_count_once_and_checks_and_verifications_do_not_contribute(checking: sqlite3.Connection, tmp_path: Path) -> None:
    unsafe_repeat(checking)
    report(checking, "implement", (100, 60, 10), 1)
    report(checking, "again", (20, 5, 2), 3)
    found = detail(checking, tmp_path)
    assert [(each.step, each.n) for each in found.attempts] == [
        ("implement", 1), ("verification", 1), ("checks", 1), ("implement", 2)]
    assert all(each.usage is None for each in found.attempts if each.step in ("checks", "verification"))
    assert found.step_usage == {"implement": Usage(55, 65, 12, 4, 2, 2)}
    assert found.usage == Usage(55, 65, 12, 4, 2, 2)


def test_incomplete_totals_sum_known_metrics_without_claiming_complete_coverage(
    registered: sqlite3.Connection, tmp_path: Path,
) -> None:
    restarted_at_plan(registered)
    report(registered, "attempt", (100, 60, 10), 1)
    report(registered, "again", (None, None, 2), None)
    found = detail(registered, tmp_path)
    assert found.step_usage == {"plan": Usage(40, 60, 12, 1, 2, 1), "implement": Usage(attempts=1)}
    assert found.usage == Usage(40, 60, 12, 1, 3, 1)


def test_interrupted_report_contributes_counts_with_incomplete_coverage(registered: sqlite3.Connection, tmp_path: Path) -> None:
    restarted_at_plan(registered)
    report(registered, "attempt", (100, 60, 10), 29, incomplete=True)
    report(registered, "again", (40, 10, 3), 16, incomplete=False)
    found = detail(registered, tmp_path)
    assert found.attempts[0].usage == Usage(40, 60, 10, 29, 1, 0)
    assert "in-flight request is missing" in found.attempts[0].summary
    assert found.step_usage["plan"] == Usage(70, 70, 13, 45, 2, 1)
    assert found.usage == Usage(70, 70, 13, 45, 3, 1)
