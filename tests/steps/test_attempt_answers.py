"""Captured answers preserve effects and discard permitted unfinished paths."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from doubles import Environment
from sqlite_store import Store
from test_attempt import ENTRY, KEY, PLAN, AttemptSurroundings, P, app, codex, database, fake, seed
from test_attempt import surroundings as attempt_surroundings

from taskloop.agents.launch import AgentLaunch
from taskloop.answer_failures import AnswerFailureData, AnswerRule
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import Answer, AnswerState, StepRules
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.ids import NativeIds
from taskloop.steps import kind

surroundings = attempt_surroundings


def test_failed_execution_valid_answer_is_not_success(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    result = app(con, surroundings, fake(rc=7)).execute(KEY, ENTRY)
    assert result.execution is not None
    assert result.execution.facts.rc == 7
    assert result.execution.facts.reason == "worker_failed"
    assert result.execution.answer.kind == "valid"


@pytest.mark.parametrize("text, kind", [("", "missing"), ("not json", "json_invalid"), ('{"plan":3}', "schema_invalid")])
def test_bad_answer_has_one_execution(tmp_path: Path, surroundings: AttemptSurroundings, text: str, kind: str) -> None:
    con = database(surroundings)
    execution = fake(text)
    result = app(con, surroundings, execution).execute(KEY, ENTRY)
    assert result.execution is not None and result.execution.answer.kind == kind
    assert len(execution.calls) == 1


@pytest.mark.parametrize(
    ("answer", "stored"),
    [
        (json.dumps(PLAN), ("planned", "commit")),
        (json.dumps(PLAN | {"disposition": "unchanged", "paths": [], "message": None}), ("unchanged", "keep")),
        (json.dumps(PLAN | {"disposition": "needs_owner", "plan_path": None, "paths": [], "message": None}), ("needs_owner", "none")),
        ("not json", (None, None)),
    ],
)
def test_the_answer_is_stored_with_its_effect(
    tmp_path: Path, surroundings: AttemptSurroundings, answer: str, stored: tuple[str | None, str | None]
) -> None:
    con = database(surroundings)
    result = app(con, surroundings, fake(answer)).execute(KEY, ENTRY)
    assert result.execution is not None and result.execution.answer.effect == stored[1]
    assert con.execute("SELECT disposition,effect FROM execution").fetchone() == stored


@pytest.mark.parametrize("step", ["plan", "implement"])
@pytest.mark.parametrize("disposition", ["incomplete", "needs_owner"])
def test_unfinished_answers_with_paths_are_collected_without_commit_or_repeat(
    surroundings: AttemptSurroundings, step: str, disposition: str
) -> None:
    con = database(surroundings)
    head = next(worktree.head for worktree in surroundings.slot.repo.worktrees() if worktree.path == surroundings.slot.path)
    con.execute("UPDATE attempt SET step=?,after_commit=?", (step, head if step == "implement" else None))
    unused = P if step == "plan" else "src/unused.py"
    answer = {"disposition": disposition, "paths": [unused, "../unused", unused], "message": None, "explanation": "Work remains"}
    if step == "plan":
        answer["plan_path"] = None
    execution = fake(json.dumps(answer))
    attempts = Attempts(
        AttemptStore(lambda: con), EvidenceFiles(surroundings.tmp), AgentLaunch(codex, ids=NativeIds()), execution, lambda: 10,
        surroundings.checkouts, surroundings.files,
        environment=Environment(con, surroundings.checkouts, surroundings.tmp, tmp_bytes=4096).preparation(),
    )
    result = attempts.execute(KEY, ENTRY, lambda: "held")
    assert (result.status, result.reason) == ("collected", disposition)
    assert result.execution is not None
    assert result.execution.answer == AnswerState("valid", disposition, "none", (), None)
    assert attempts.collect(KEY) == result and attempts.execute(KEY, ENTRY) == result
    assert len(execution.calls) == 1
    assert con.execute("SELECT disposition,effect,commit_paths,commit_message FROM execution").fetchone() == (
        disposition, "none", "[]", None)
    raw = EvidenceFiles(surroundings.tmp).text(KEY, "answer.txt")
    assert raw is not None and json.loads(raw) == answer


@pytest.mark.parametrize(("text", "rule", "detail"), [
    ("", AnswerRule.MISSING, "empty"),
    ("not json", AnswerRule.JSON, "strict JSON"),
    ('{"disposition":1,"disposition":2}', AnswerRule.JSON, "strict JSON"),
    ('{"plan":3}', AnswerRule.SHAPE, "exactly"),
    (json.dumps(PLAN | {"paths": [P, P]}), AnswerRule.PATHS_DUPLICATE, "unique"),
    (json.dumps(PLAN | {"message": None}), AnswerRule.MESSAGE, "1 to 500"),
])
def test_failure_survives_reopening_and_missing_raw_answer(
    surroundings: AttemptSurroundings, text: str, rule: AnswerRule, detail: str,
) -> None:
    path = surroundings.tmp / "factory.db"
    con = Store(SCHEMA).open_rw(path)
    assert con is not None
    seed(con, surroundings)
    execution = fake(text)
    owner = app(con, surroundings, execution)
    result = owner.execute(KEY, ENTRY)
    assert result.execution is not None and result.execution.verification is None
    failure = result.execution.answer.failure
    assert failure is not None and failure.rule is rule and detail in failure.explanation
    assert failure.describe() in result.explanation and result.execution.answer.effect is None
    loaded = owner.store.load(KEY)
    assert loaded is not None
    state, evidence = result.execution.answer, result.execution.evidence
    assert owner.store.answer(loaded.admission, evidence, state) == "already_same"
    changed = replace(state, failure=AnswerFailureData(rule=rule, explanation="Another failure"))
    assert owner.store.answer(loaded.admission, evidence, changed) == "conflict"
    assert owner.store.answer(loaded.admission, evidence, AnswerState("valid", "planned", "commit", (P,), "Plan")) == "conflict"
    con.close()
    EvidenceFiles(surroundings.tmp).read(evidence.answer)
    (surroundings.tmp / evidence.answer.path).unlink()
    reopened = Store(SCHEMA).open_rw(path)
    assert reopened is not None
    try:
        reader = app(reopened, surroundings, execution)
        assert reader.collect(KEY) == result and reader.collect(KEY) == result
        assert len(execution.calls) == 1
        for malformed in (
            {"rule": "unknown", "explanation": "bad"},
            {"rule": rule},
            {"rule": rule, "explanation": "x" * 2001},
            {"rule": rule, "explanation": "bad", "extra": 1},
            {"rule": AnswerRule.JSON if rule is AnswerRule.MISSING else AnswerRule.MISSING, "explanation": "Wrong phase"},
            [],
        ):
            reopened.execute("UPDATE execution SET answer_failure=?", (json.dumps(malformed),))
            assert reader.collect(KEY).status == "unavailable"
    finally:
        reopened.close()


def test_unexpected_value_error_is_not_an_answer_rejection(surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch) -> None:
    con = database(surroundings)
    owner = app(con, surroundings, fake())
    operation = kind("plan")

    def broken(_value: object, _rules: StepRules) -> Answer:
        raise ValueError("decoder bug")

    monkeypatch.setattr("taskloop.attempt.kind", lambda _step: replace(operation, decode=broken))
    with pytest.raises(ValueError, match="decoder bug"):
        owner.execute(KEY, ENTRY)
    assert owner.collect(KEY).reason == "validation_pending"
