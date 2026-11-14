"""Captured answers preserve effects and discard permitted unfinished paths."""

import json
from pathlib import Path

import pytest
from doubles import Environment
from test_attempt import ENTRY, KEY, PLAN, AttemptSurroundings, P, app, codex, database, fake
from test_attempt import surroundings as attempt_surroundings

from taskloop.agents.launch import AgentLaunch
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AnswerState
from taskloop.evidence_files import EvidenceFiles
from taskloop.ids import NativeIds

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
