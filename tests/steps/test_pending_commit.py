"""A pending factory commit keeps collection and scheduling at the same boundary."""

import json
from dataclasses import replace

import pytest

from taskloop.attempt_result import PendingReason, report, succeeded
from taskloop.attempt_status import EntryState, next_action
from taskloop.attempt_types import (
    AnswerState,
    AttemptKey,
    AttemptResult,
    Evidence,
    ExecutionFacts,
    FileRef,
    StoredExecution,
)

REF = FileRef("facts", "digest")
COMPLETE = StoredExecution(
    AttemptKey("attempt", "dispatch", 1),
    ExecutionFacts(0, False, None, None, False, False, None, None, None, None, None, None, None),
    Evidence(REF, REF, REF, REF),
    AnswerState("valid", "planned", "commit"),
    "complete",
)


@pytest.mark.parametrize("answer", [
    AnswerState("valid", "planned", "commit"),
    AnswerState("valid", "implemented", "commit"),
    AnswerState("valid", "unchanged", "keep"),
])
def test_valid_answers_without_a_verdict_wait_for_commit(answer: AnswerState) -> None:
    result = report(replace(COMPLETE, answer=answer))
    assert result.reason is PendingReason.COMMIT and not succeeded(result)
    assert json.dumps({"status": result.status, "reason": result.reason}) == '{"status": "pending", "reason": "commit"}'


@pytest.mark.parametrize(("entry", "expected"), [
    ("none", "verify"), ("gone", "verify"), ("different_process", "verify"), ("running", "wait"), ("unknown", "unknown"),
])
@pytest.mark.parametrize("with_execution", [False, True])
def test_commit_pending_preserves_the_next_action(entry: EntryState, expected: str, with_execution: bool) -> None:
    result = report(COMPLETE) if with_execution else AttemptResult("pending", PendingReason.COMMIT)
    assert next_action("captured", entry, result, False) == expected
    if entry != "running":
        assert next_action("captured", entry, result, True) == expected


@pytest.mark.parametrize(("phase", "expected"), [("admitted", "start"), ("dispatching", "release"), ("registered", "release")])
def test_a_missing_execution_keeps_its_existing_phase_action(phase: str, expected: str) -> None:
    assert next_action(phase, "gone", AttemptResult("pending", PendingReason.COMMIT), False) == expected


@pytest.mark.parametrize(("stored", "reason"), [
    (replace(COMPLETE, answer=AnswerState("validation_pending")), "validation_pending"),
    (replace(COMPLETE, session_state="pending"), "session_pending"),
    (replace(COMPLETE, session_state="fault"), "session_fault"),
])
def test_unfinished_capture_still_precedes_the_commit_wait(stored: StoredExecution, reason: str) -> None:
    result = report(stored)
    assert (result.status, result.reason) == ("pending", reason) and not succeeded(result)
    assert next_action("captured", "gone", result, False) == "verify"
