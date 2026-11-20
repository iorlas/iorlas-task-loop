"""Deciding operations capture typed causes once, before effects; retries use that snapshot."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from test_hold import VIEW, Bench
from test_hold_store import attempt

from taskloop.answer_failures import AnswerFailureData, AnswerRule
from taskloop.attempt_status import AttemptView, Next, with_hold
from taskloop.attempt_types import AnswerState, AttemptKey, AttemptResult, Evidence, ExecutionFacts, FileRef, Rejected, StoredExecution
from taskloop.check_status import ChecksView
from taskloop.check_store import CheckStore
from taskloop.hold import hold_task
from taskloop.hold_store import HoldStore
from taskloop.step import Step
from taskloop.task_event import EventStep
from taskloop.task_event_cause import (
    AnswerCause,
    DispositionCause,
    LandCause,
    LandReason,
    MergeCause,
    MergeReason,
    RejectionCause,
    RepeatCause,
    RoundCause,
    RoundReason,
    RunCause,
    StuckCause,
    StuckReason,
)


@pytest.fixture
def bench(factory: sqlite3.Connection, tmp_path: Path) -> Bench:
    attempt(factory, "a")
    return Bench(factory, tmp_path)


def execution(root: Path, step: Step = Step.PLAN) -> StoredExecution:
    answer = {"disposition": "needs_owner", "plan_path": None, "paths": [], "message": None, "explanation": "Choose the database."}
    if step is Step.IMPLEMENT:
        answer.pop("plan_path")
        answer.pop("paths")
    path = root / "answer.json"
    path.write_text(json.dumps(answer))
    ref = FileRef("answer.json", hashlib.sha256(path.read_bytes()).hexdigest())
    facts = ExecutionFacts(
        rc=0,
        timed_out=False,
        stop=None,
        watch=None,
        work=True,
        stands=True,
        answered=True,
        reason=None,
        http_status=None,
        tokens=None,
        cumulative=None,
        turns=None,
        session=None,
    )
    return StoredExecution(
        AttemptKey("a", "a-token", 1), facts, Evidence(ref, ref, ref, ref), AnswerState("valid", "needs_owner", "none"), "complete"
    )


@pytest.mark.parametrize("failure", ["disposition", "run", "answer", "rejection"])
@pytest.mark.parametrize("step", [Step.PLAN, Step.IMPLEMENT])
def test_agent_decisions_use_structured_execution_and_causal_step(bench: Bench, failure: str, step: Step) -> None:
    stored = execution(bench.root, step)
    expected = DispositionCause
    if failure == "run":
        stored = replace(stored, facts=replace(stored.facts, rc=-9, timed_out=True, reason="timeout"))
        expected = RunCause
    elif failure == "answer":
        rejected = AnswerFailureData(rule=AnswerRule.JSON, explanation="The answer was truncated.")
        stored = replace(stored, answer=AnswerState("json_invalid", failure=rejected))
        expected = AnswerCause
    elif failure == "rejection":
        stored = replace(stored, verdict=Rejected("paths"))
        expected = RejectionCause
    bench.con.execute("UPDATE attempt SET step=?,after_commit=?", (str(step), "d" * 40 if step is Step.IMPLEMENT else None))
    view = replace(VIEW, step=str(step), result=AttemptResult("collected", "display text is not a codec", stored))
    assert hold_task(bench.ports(view), view).word == "held"
    captured = bench.row().event
    assert (captured.attempt_id, captured.cause_id, captured.agent_step, captured.step) == ("a", "a", step, EventStep(step))
    assert isinstance(captured.cause, expected)
    if isinstance(captured.cause, RunCause):
        assert (captured.cause.deadline, captured.cause.timed_out, captured.cause.rc) == (100.0, True, -9)
    if isinstance(captured.cause, AnswerCause):
        assert captured.cause.failure == stored.answer.failure


def test_answer_changes_after_recording_cannot_change_a_retry(bench: Bench) -> None:
    stored = execution(bench.root)
    view = replace(VIEW, result=AttemptResult("collected", "needs_owner", stored))
    bench.tracker.commented = "unavailable"
    assert hold_task(bench.ports(view), view).missing == "comment"
    captured = bench.row().event
    (bench.root / "answer.json").write_text("changed evidence")
    restarted = Bench(bench.con, bench.root, now=20.0)
    changed = replace(view, result=AttemptResult("collected", "run:timeout"))
    assert hold_task(restarted.ports(changed), changed).word == "held"
    assert restarted.row().event == captured
    assert "> Choose the database." in restarted.tracker.texts[0]
    assert "run:timeout" not in restarted.tracker.texts[0]


@pytest.mark.parametrize("action", ["stuck:entry_lost", "repeats_exhausted"])
def test_stuck_and_repeat_decisions_survive_the_hold_projection(bench: Bench, action: Next) -> None:
    raw = replace(VIEW, next=action, hold_due=None, result=AttemptResult("pending"), leftovers=("unsafe", "src/kept.py"))
    view = with_hold(raw, None)
    bench.tracker.commented = "unavailable"
    assert hold_task(bench.ports(view), view).missing == "comment"
    recorded = bench.row().event
    captured = bench.row().event.cause
    if isinstance(captured, StuckCause):
        assert captured.reason is StuckReason.ENTRY_LOST
    else:
        assert isinstance(captured, RepeatCause) and captured.leftovers is not None
        assert captured.leftovers.paths == ("src/kept.py",)
    bench.con.execute("UPDATE attempt SET deadline=999")
    restarted = Bench(bench.con, bench.root, now=30.0)
    changed = replace(view, leftovers=("ignored", "changed.py"))
    assert hold_task(restarted.ports(changed), changed).word == "held"
    assert restarted.row().event == recorded and "changed.py" not in restarted.tracker.texts[0]
    if isinstance(captured, RepeatCause):
        assert "src/kept.py" in restarted.tracker.texts[0]


def test_checks_capture_colon_names_and_failed_results_before_retry(checking: sqlite3.Connection, tmp_path: Path) -> None:
    checking.execute("UPDATE attempt SET label='auto'")
    checking.execute(
        "INSERT INTO check_result VALUES ('checks',1,0,'test:unit','checks-token',1,?,60,NULL,NULL,NULL,NULL,1,2,1,'failed')", ("e" * 64,)
    )
    checks = CheckStore(lambda: checking).of_attempt("implement")[0]
    view = AttemptView(
        "tasks",
        "tl-1",
        "check",
        "checks",
        "s2",
        "concluded",
        "gone",
        AttemptResult("collected", "ignored display"),
        False,
        "hold",
        label="auto",
        hold_due="ignored display",
        checks=ChecksView(replace(checks, reason="test:unit:failed"), ()),
    )
    bench = Bench(checking, tmp_path)
    bench.tracker.commented = "unavailable"
    assert hold_task(bench.ports(view), view).missing == "comment"
    captured = bench.row("implement").event
    assert (captured.attempt_id, captured.cause_id, captured.step) == ("implement", "checks", EventStep.CHECK)
    checking.execute("UPDATE check_result SET conclusion='passed',rc=0")
    restarted = Bench(checking, tmp_path, now=30.0)
    assert hold_task(restarted.ports(view), view).word == "held"
    assert restarted.row("implement").event == captured
    assert "Failed checks: test:unit failed" in restarted.tracker.texts[0]


@pytest.mark.parametrize(
    "decided",
    [
        RoundCause(reason=RoundReason.CLAIM_LOST, explanation="The claim changed."),
        LandCause(reason=LandReason.REMOTE_REJECTED, explanation="The remote requires review."),
    ],
)
def test_round_and_land_decisions_capture_the_refusal(bench: Bench, decided: RoundCause | LandCause) -> None:
    view = replace(VIEW, next="land" if isinstance(decided, LandCause) else "advance", hold_due=None)
    bench.fresh = view
    assert hold_task(bench.ports(view), view, decided).word == "held"
    assert bench.row().event.cause == decided


def test_merge_decision_captures_retained_context(bench: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    retained = MergeCause(
        reason=MergeReason.NEEDS_OWNER,
        explanation="Choose the retained resolution.",
        source="source",
        target="target",
        conflicts=("src/conflict.py",),
    )
    monkeypatch.setattr("taskloop.hold_event.merge_cause", lambda _reader, _attempt_id: retained)
    view = replace(VIEW, result=AttemptResult("refused", "ignored display"))
    assert hold_task(bench.ports(view), view).word == "held"
    assert bench.row().event.cause == retained


def test_missing_mandatory_context_has_no_record_or_external_effects(bench: Bench) -> None:
    view = replace(VIEW, result=AttemptResult("collected", "needs_owner", execution(bench.root)))
    (bench.root / "answer.json").unlink()
    assert hold_task(bench.ports(view), view).refusal == "unavailable:store"
    assert HoldStore(lambda: bench.con).of_attempts(("a",)) == {} and bench.calls == []
