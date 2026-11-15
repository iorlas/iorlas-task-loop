"""Agent-step text round-trips through one codec; in-process evidence stays strict."""

import pytest
from pydantic import ValidationError

from taskloop.attempt_types import AttemptKey
from taskloop.earlier_attempt import EarlierAttempt
from taskloop.step import Step, decode_step, encode_step


@pytest.mark.parametrize(("step", "text"), [(Step.PLAN, "plan"), (Step.IMPLEMENT, "implement")])
def test_step_codec_preserves_member_identity_and_external_text(step: Step, text: str) -> None:
    assert encode_step(step) == text
    assert type(encode_step(step)) is str
    assert decode_step(text) is step
    assert decode_step(encode_step(step)) is step


@pytest.mark.parametrize("text", ["", "unknown", "PLAN", "Implement", " plan", "implement ", "check"])
def test_step_codec_rejects_every_noncanonical_spelling(text: str) -> None:
    with pytest.raises(ValueError):
        decode_step(text)


@pytest.mark.parametrize("step", list(Step))
def test_earlier_attempt_requires_an_enum_member_in_process(step: Step) -> None:
    fields = {
        "key": AttemptKey("attempt", "dispatch", 1), "revision": 1, "repo_id": "repo", "backlog": "tasks",
        "task_id": "tl-1", "tracker_root": "/tracker", "slot": "slot", "step": step, "end_commit": None,
    }
    earlier = EarlierAttempt.model_validate(fields)
    assert earlier.step is step
    with pytest.raises(ValidationError, match="step"):
        EarlierAttempt.model_validate(fields | {"step": encode_step(step)})
