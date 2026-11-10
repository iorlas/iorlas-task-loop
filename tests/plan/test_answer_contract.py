"""The answer contract: the schema Codex forwards as a strict response format, the decoder that owns the cross-field rule,
and the terminal outcome a collected result reports."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from taskloop.plan import outcome, report, succeeded
from taskloop.plan_files import PlanFiles
from taskloop.plan_types import (
    AnswerState,
    AttemptKey,
    AttemptResult,
    Evidence,
    ExecutionFacts,
    FileRef,
    StoredExecution,
    decode_plan_answer,
)

KEY = AttemptKey("attempt", "dispatch", 1)
EXPECTED = "docs/design/tl-1/plan.md"
# OpenAI strict structured output: the root is a plain object, and these may not appear at the root
ROOT_FORBIDDEN = {"oneOf", "anyOf", "allOf", "enum", "not", "if", "then", "else", "const", "$ref", "$defs"}
# conservative: no composition or conditional keyword anywhere, only the documented strict-mode keywords
ALLOWED = {"type", "properties", "required", "additionalProperties", "enum", "pattern", "items", "description"}


def schema(tmp_path: Path) -> dict[str, object]:
    path, _answer = PlanFiles(tmp_path).prepare(KEY)
    loaded = json.loads(Path(path).read_text())
    assert isinstance(loaded, dict)
    return loaded


def nodes(node: object) -> Iterator[dict[str, object]]:
    """Every schema node: the root, each property schema and each array item schema."""
    if isinstance(node, dict):
        yield node
        properties = node.get("properties", {})
        assert isinstance(properties, dict)
        for child in properties.values():
            yield from nodes(child)
        yield from nodes(node.get("items"))


def test_the_root_is_a_plain_object_with_every_property_required(tmp_path: Path) -> None:
    root = schema(tmp_path)
    assert root["type"] == "object" and root["additionalProperties"] is False
    assert not ROOT_FORBIDDEN & set(root)
    properties, required = root["properties"], root["required"]
    assert isinstance(properties, dict) and isinstance(required, list) and sorted(required) == sorted(properties)


def test_no_node_uses_composition_conditionals_or_unlisted_keywords(tmp_path: Path) -> None:
    for node in nodes(schema(tmp_path)):
        assert set(node) <= ALLOWED, set(node) - ALLOWED
        if node.get("type") == "object":
            properties, required = node.get("properties"), node.get("required")
            assert node.get("additionalProperties") is False
            assert isinstance(properties, dict) and isinstance(required, list) and set(required) == set(properties)


PLANNED = {"disposition": "planned", "plan_path": EXPECTED, "commit": "a" * 40, "explanation": "done"}


@pytest.mark.parametrize(
    "change",
    [{"plan_path": None}, {"plan_path": "docs/design/tl-2/plan.md"}, {"commit": None}, {"commit": "A" * 40}, {"explanation": "x" * 2001}],
    ids=["planned_without_path", "planned_with_another_path", "planned_without_commit", "bad_commit", "long_explanation"],
)
def test_the_decoder_alone_owns_the_rules_the_schema_leaves_out(change: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="Invalid plan answer"):
        decode_plan_answer(PLANNED | change, EXPECTED)


def test_the_decoder_accepts_planned_with_path_and_commit_and_incomplete_with_nulls() -> None:
    assert decode_plan_answer(PLANNED, EXPECTED).commit == "a" * 40
    incomplete = decode_plan_answer(PLANNED | {"disposition": "incomplete", "plan_path": None, "commit": None}, EXPECTED)
    assert (incomplete.disposition, incomplete.plan_path, incomplete.commit) == ("incomplete", None, None)


def stored(rc: int | None, timed_out: bool, reason: str | None, answer: AnswerState) -> StoredExecution:
    ref = FileRef("f", "d")
    facts = ExecutionFacts(rc, timed_out, None, None, False, False, None, reason, None, None, None, None, None)
    return StoredExecution(KEY, facts, Evidence(ref, ref, ref, ref), answer, "complete")


VALID = AnswerState("valid", "planned", EXPECTED, "a" * 40)


@pytest.mark.parametrize(
    ("rc", "timed_out", "reason", "answer", "expected"),
    [
        (0, False, None, VALID, "planned"),
        (0, False, None, AnswerState("valid", "incomplete"), "incomplete"),
        (1, False, "bad_request", AnswerState("missing"), "run:bad_request"),
        (7, False, "worker_failed", VALID, "run:worker_failed"),
        (None, True, "timeout", VALID, "run:timeout"),
        (None, True, None, VALID, "run:timeout"),
        (1, False, None, VALID, "run:exit"),
        (0, False, None, AnswerState("missing"), "answer:missing"),
        (0, False, None, AnswerState("json_invalid"), "answer:json_invalid"),
        (0, False, None, AnswerState("schema_invalid"), "answer:schema_invalid"),
    ],
)
def test_collected_always_names_its_outcome_and_success_needs_a_clean_valid_run(
    rc: int | None, timed_out: bool, reason: str | None, answer: AnswerState, expected: str
) -> None:
    result = report(stored(rc, timed_out, reason, answer))
    assert (result.status, result.reason) == ("collected", expected) and outcome(stored(rc, timed_out, reason, answer)) == expected
    assert succeeded(result) is (expected in ("planned", "incomplete"))


def test_only_collected_can_succeed() -> None:
    assert not succeeded(AttemptResult("pending", "planned"))
