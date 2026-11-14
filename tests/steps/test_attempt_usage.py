"""Stream usage survives terminal outcomes, capture replay and independent collection."""

import json
from dataclasses import replace

import pytest
from any_agent import RunOutcome, Summary
from any_agent.testing import FakeRun
from test_attempt import ENTRY, KEY, PLAN, WORKER, AttemptSurroundings, app, database
from test_attempt import surroundings as attempt_surroundings

from taskloop.attempt_status import Shown, StatusPorts, show_attempt
from taskloop.step_render import human

surroundings = attempt_surroundings


@pytest.mark.parametrize(("rc", "timed_out", "stop", "answer", "reason"), [
    (-9, False, None, "", "run:killed"),
    (-9, True, "timeout", "", "run:timeout"),
    (-15, False, "answer", json.dumps(PLAN), "run:killed"),
    (0, False, "answer", json.dumps(PLAN), "verification"),
    (0, False, None, "not json", "answer:json_invalid"),
])
@pytest.mark.parametrize("incomplete", [True, False, None, "invalid", 1])
def test_usage_survives_endings_and_capture_replay(
    surroundings: AttemptSurroundings, rc: int, timed_out: bool, stop: str | None, answer: str, reason: str,
    incomplete: bool | str | int | None,
) -> None:
    con = database(surroundings)
    raw = RunOutcome(rc=rc, timed_out=timed_out, stop=stop, worker=WORKER, summary=Summary(
        rc=rc, text=answer, res={"tokens": {"in": 740000, "cached": 600000, "out": 1500},
                               "cumulative": {"in": 1790000, "cached": 1000000, "out": 3000},
                               "turns": 16, "usage_incomplete": incomplete}))
    execution = FakeRun(raw)
    owner = app(con, surroundings, execution)
    result = owner.execute(KEY, ENTRY)
    assert result.reason == reason and result.execution is not None
    stored = result.execution
    facts = stored.facts
    assert facts.tokens == (740000, 600000, 1500)
    assert facts.cumulative == (1790000, 1000000, 3000) and facts.turns == 16
    assert facts.usage_incomplete is (incomplete if isinstance(incomplete, bool) else None)
    assert con.execute("SELECT t_in,t_cached,t_out,c_in,c_cached,c_out,turns,usage_incomplete FROM execution").fetchone() == (
        740000, 600000, 1500, 1790000, 1000000, 3000, 16, facts.usage_incomplete)
    loaded = owner.store.load(KEY)
    assert loaded is not None
    assert owner.store.capture(loaded.admission, WORKER, facts, stored.evidence, "complete") == "already_same"
    changed = replace(facts, usage_incomplete=not facts.usage_incomplete)
    assert owner.store.capture(loaded.admission, WORKER, changed, stored.evidence, "complete") == "conflict"
    unused = FakeRun(raw)
    reader = app(con, surroundings, unused)
    assert reader.collect(KEY) == result and reader.execute(KEY, ENTRY) == result
    assert len(execution.calls) == 1 and unused.calls == []
    if incomplete is True:
        assert "in-flight request is missing" in result.explanation
        assert reason in result.explanation or reason == "answer:json_invalid"
    if reason == "answer:json_invalid":
        assert stored.answer.failure is not None and stored.answer.failure.describe() in result.explanation
    ports = StatusPorts(owner.store, lambda _entry: "gone", lambda: 30, lambda _key: None, lambda: "boot")
    shown = show_attempt(ports, surroundings.tmp, "tasks", "tl-1")
    assert isinstance(shown, Shown)
    if incomplete is True:
        assert "in-flight request is missing" in "\n".join(human("show", shown, None))


@pytest.mark.parametrize(("tokens", "turns", "words"), [
    (None, None, "Usage was not reported by the agent stream."),
    ((0, 0, 0), 0, ""),
    ((20, None, 3), None, "Usage was not reported for: cached input tokens, turns."),
])
def test_missing_and_zero_usage_in_attempt_views(
    surroundings: AttemptSurroundings, tokens: tuple[int | None, int | None, int | None] | None, turns: int | None, words: str,
) -> None:
    con = database(surroundings)
    counts = None if tokens is None else dict(zip(("in", "cached", "out"), tokens, strict=True))
    execution = FakeRun(RunOutcome(rc=0, stop="answer", worker=WORKER, summary=Summary(
        text=json.dumps(PLAN), res={"tokens": counts, "turns": turns})))
    owner = app(con, surroundings, execution)
    result = owner.execute(KEY, ENTRY)
    assert result.execution is not None
    assert result.execution.facts.tokens == tokens and result.execution.facts.turns == turns
    if words:
        assert words in result.explanation
    else:
        assert result.explanation == ""
    ports = StatusPorts(owner.store, lambda _entry: "gone", lambda: 30, lambda _key: None, lambda: "boot")
    shown = show_attempt(ports, surroundings.tmp, "tasks", "tl-1")
    assert isinstance(shown, Shown)
    text = "\n".join(human("show", shown, None))
    assert words in text if words else "Usage was not reported" not in text
