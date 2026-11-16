"""Land and hold guidance explains decisions without prescribing command invocations."""

from dataclasses import replace
from pathlib import Path

import pytest
from hold_fixtures import event_for, events, row

from taskloop.attempt_status import AttemptView, Shown
from taskloop.attempt_types import AttemptResult
from taskloop.exit_codes import ExitCode, exit_code
from taskloop.hold_guide import HOLD, ON_HOLD, hold_guide, pending_guide
from taskloop.hold_store import Labels
from taskloop.land_guide import CANDIDATE_RELEASE, INTERRUPTED, LAND_GUIDE, LAND_NEXT, restart
from taskloop.operations import Failed, Move, Round
from taskloop.step_guide import guide
from taskloop.step_render import human
from taskloop.task_event_codec import reason as event_reason

VIEW = AttemptView("tasks", "tl-1", "plan", "a", "s1", "captured", "gone",
                   AttemptResult("collected", "needs_owner"), False, "on_hold", label="approved")
ROW = row(label="approved")


def assert_prose(text: str) -> None:
    assert len(text.split()) >= 8
    assert all(token not in text for token in ("tl step", "bd ", "git ", "ps -", "--")), text


@pytest.mark.parametrize("reason", LAND_GUIDE)
def test_land_refusals_render_their_command_free_guide(reason: str) -> None:
    lines = human("tl step land", Failed("refused", reason), None)
    assert LAND_GUIDE[reason] in lines
    for text in lines[1:]:
        assert_prose(text)


@pytest.mark.parametrize("word", LAND_NEXT)
def test_land_status_guides_keep_the_land_context(word: str) -> None:
    text = guide(word, checks=True, land=True)
    assert text == LAND_NEXT[word]
    assert_prose(text)


@pytest.mark.parametrize("reason", CANDIDATE_RELEASE)
def test_candidate_release_uses_release_advice_before_shared_step_advice(reason: str) -> None:
    lines = human("tl step release", Failed("unavailable", reason, land=True), None)
    assert CANDIDATE_RELEASE[reason] in lines and LAND_GUIDE["unavailable"] not in lines
    for text in lines[1:]:
        assert_prose(text)


def test_land_decisions_retain_delivery_and_retry_safety() -> None:
    assert "Manual land is the default" in LAND_NEXT["land"]
    assert "last free slot" in LAND_NEXT["land"] and "automatic land" in LAND_NEXT["land"]
    assert "review the diff and accept" in LAND_GUIDE["gate_changed"]
    assert "same validated candidate" in LAND_GUIDE["remote_rejected"]
    assert "already on main" in LAND_GUIDE["blocked"]
    assert "missing work" in LAND_GUIDE["unavailable"]
    assert "keeping the decision to abandon" in CANDIDATE_RELEASE["unavailable"]
    assert_prose(restart("tl-1", "a" * 40))
    failed = Failed("unavailable", INTERRUPTED)
    assert exit_code(failed) == ExitCode.INTERRUPTED
    assert "whole block" in human("tl step land", failed, None)[-2]


@pytest.mark.parametrize("reason", [event_reason(each) for each in events()])
def test_known_hold_causes_cannot_forward_command_recipes(reason: str) -> None:
    text = hold_guide(replace(VIEW, hold=ROW.model_copy(update={"event": event_for(reason)})))
    assert_prose(text)
    if reason == "land:conflict" or reason.startswith("merge:"):
        assert "stays held" in text and "do not restart" in text
    else:
        assert "approval label `approved`" in text and "close the task" in text


@pytest.mark.parametrize("recorded", [True, False])
def test_unanswered_holds_explain_answers_and_the_retained_branch(recorded: bool) -> None:
    text = hold_guide(replace(VIEW, hold=ROW if recorded else None))
    assert_prose(text)
    assert "description or acceptance criteria" in text and "not comments" in text
    assert "approval label" in text and "again at plan" in text and "close the task" in text
    if not recorded:
        assert text == ON_HOLD


@pytest.mark.parametrize("labels", ["closed", "missing", "not_ours", "moved"])
def test_hold_recovery_respects_tracker_ownership(labels: Labels) -> None:
    text = hold_guide(replace(VIEW, hold=ROW.model_copy(update={"labels": labels})))
    assert_prose(text)
    if labels in ("closed", "missing"):
        assert "nothing to answer" in text and "approval label" not in text
    elif labels == "not_ours":
        assert "manual continuation with the current owner" in text and "rounds do not take it again" in text
        assert "restore" not in text
    else:
        assert "approval label `approved`" in text and "task/tl-1 as it is" in text


def test_a_hold_without_a_recorded_approval_label_requires_manual_continuation() -> None:
    text = hold_guide(replace(VIEW, hold=ROW.model_copy(update={"label": None})))
    assert_prose(text)
    assert "choose manual continuation" in text and "no approval label was recorded" in text


@pytest.mark.parametrize(("reason", "situation", "decision"), [
    ("failed:run:timeout", "did not finish before its deadline", "allow more time"),
    ("branch_moved", "Held:", "First restore task/tl-1 to contain the commit accepted by factory commit"),
    ("claim_lost", "Someone else changed this task's claim", "approval label `approved`"),
    ("land:checks_failed", "checks failed", "preserve the old task branch and restart from plan"),
])
def test_shown_holds_keep_the_cause_and_decision_in_prose(
    reason: str, situation: str, decision: str, tmp_path: Path,
) -> None:
    view = replace(VIEW, hold=ROW.model_copy(update={"event": event_for(reason)}))
    shown = Shown(view, tmp_path, tmp_path / "entry.log", tmp_path / "events.jsonl")
    text = human("show", shown, tmp_path / "factory.db")[-1]
    assert text == hold_guide(view) and situation in text and decision in text
    assert_prose(text)


@pytest.mark.parametrize("recorded", [True, False])
@pytest.mark.parametrize("reason", ["land:conflict", "merge:needs_owner"])
def test_terminal_holds_stay_held_with_their_retained_work(reason: str, recorded: bool) -> None:
    held = ROW.model_copy(update={"event": event_for(reason)}) if recorded else None
    view = replace(VIEW, next="on_hold" if recorded else "hold", hold=held,
                   hold_due=None if recorded else reason)
    text = hold_guide(view)
    assert_prose(text)
    assert "retained task work" in text and "stays held" in text and "do not restart" in text
    assert "To answer" not in text and "To continue" not in text


@pytest.mark.parametrize("recorded", [True, False])
def test_pending_holds_keep_their_waiting_condition(recorded: bool) -> None:
    text = hold_guide(replace(VIEW, next="hold", hold=ROW if recorded else None, hold_due=ROW.reason))
    assert text == HOLD and "next round returns the claim" in text
    assert_prose(text)
    word = "pending abandon held:slot_dirty"
    lines = human("next", Round("tasks", (Move("tl-1", "hold", word, "a", step="plan"),)), None)
    assert lines[-1] == f"hold: {pending_guide(word)}"
    assert_prose(lines[-1])
