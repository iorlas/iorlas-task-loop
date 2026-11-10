"""The answer contract: the five-key schema Codex forwards as a strict response format, the decoder that owns every bound
and cross-field rule (the listed paths, the message, `unchanged`), and the terminal outcome a collected result reports,
a planned or unchanged one only with its verdict."""

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
    Rejected,
    StageRules,
    StoredExecution,
    Verdict,
    Verified,
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


RULES = StageRules("docs/design/tl-1/")
D = "docs/design/tl-1/"
PLANNED = {"disposition": "planned", "plan_path": EXPECTED, "paths": [EXPECTED], "message": "Plan tl-1", "explanation": "done"}
UNCHANGED = {"disposition": "unchanged", "plan_path": EXPECTED, "paths": [], "message": None, "explanation": "still valid"}


def test_the_schema_has_the_five_keys_and_the_unchanged_disposition(tmp_path: Path) -> None:
    root = schema(tmp_path)
    properties = root["properties"]
    assert isinstance(properties, dict) and sorted(properties) == ["disposition", "explanation", "message", "paths", "plan_path"]
    disposition = properties["disposition"]
    assert isinstance(disposition, dict) and disposition["enum"] == ["planned", "unchanged", "incomplete", "needs_owner"]
    assert properties["paths"] == {"type": "array", "items": {"type": "string"}}  # bounds live in the decoder alone


BAD_PATHS = [
    D + "../escape.md", D + ".GIT/hooks", D + ".github/x", D + ".gitkeep", D + "sub//x.md", D + "./x.md", "docs/design/tl-2/x.md",
    "src/x.py", "/" + EXPECTED, D + ".g\u200cit/x", D + ".\ufeffGit", D + "a\\b", D + "a\nb", D + "a\0b", D + "x" * 256, D,
]


@pytest.mark.parametrize(
    "change",
    [
        {"plan_path": None},
        {"plan_path": "docs/design/tl-2/plan.md"},
        {"paths": []},
        {"paths": [D + "note.md"]},
        {"paths": [EXPECTED, EXPECTED]},
        {"paths": [EXPECTED, *(f"{D}n{i}.md" for i in range(32))]},
        {"paths": EXPECTED},
        {"paths": [EXPECTED, 3]},
        *({"paths": [EXPECTED, bad]} for bad in BAD_PATHS),
        {"message": None},
        {"message": ""},
        {"message": "x" * 501},
        {"message": "Plan\0"},
        {"message": "Plan\n\nTask-Loop-Attempt: other"},
        {"message": "Plan\n\ntask-loop-attempt: other"},
        {"explanation": "x" * 2001},
        {"commit": "a" * 40},
    ],
)
def test_the_decoder_alone_owns_the_rules_and_bounds_the_schema_leaves_out(change: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="Invalid plan answer"):
        decode_plan_answer(PLANNED | change, RULES)


def test_an_old_four_key_answer_is_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid plan answer"):
        decode_plan_answer({"disposition": "planned", "plan_path": EXPECTED, "commit": "a" * 40, "explanation": "x"}, RULES)


@pytest.mark.parametrize(
    "change",
    [{"paths": [EXPECTED]}, {"message": "Plan"}, {"plan_path": None}, {"plan_path": "docs/design/tl-2/plan.md"}],
    ids=["paths", "message", "no_plan_path", "other_plan_path"],
)
def test_unchanged_changes_nothing_and_names_the_expected_plan(change: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="Invalid plan answer"):
        decode_plan_answer(UNCHANGED | change, RULES)


def test_the_decoder_accepts_each_disposition_in_its_shape() -> None:
    many = [EXPECTED, *(f"{D}n{i}.md" for i in range(31))]
    planned = decode_plan_answer(PLANNED | {"paths": many, "message": "x" * 500}, RULES)
    assert (planned.paths, planned.message) == (tuple(many), "x" * 500)
    unchanged = decode_plan_answer(UNCHANGED, RULES)
    assert (unchanged.disposition, unchanged.plan_path, unchanged.paths, unchanged.message) == ("unchanged", EXPECTED, (), None)
    for disposition in ("incomplete", "needs_owner"):
        for path in (None, EXPECTED):
            found = decode_plan_answer(UNCHANGED | {"disposition": disposition, "plan_path": path}, RULES)
            assert (found.disposition, found.plan_path, found.paths) == (disposition, path, ())
    with pytest.raises(ValueError, match="Invalid plan answer"):
        decode_plan_answer(UNCHANGED | {"disposition": "incomplete", "paths": [EXPECTED]}, RULES)


def stored(rc: int | None, timed_out: bool, reason: str | None, answer: AnswerState, verdict: Verdict | None = None) -> StoredExecution:
    ref = FileRef("f", "d")
    facts = ExecutionFacts(rc, timed_out, None, None, False, False, None, reason, None, None, None, None, None)
    return StoredExecution(KEY, facts, Evidence(ref, ref, ref, ref), answer, "complete", verdict)


VALID = AnswerState("valid", "planned", EXPECTED, (EXPECTED,), "Plan tl-1")
REUSE = AnswerState("valid", "unchanged", EXPECTED)


@pytest.mark.parametrize(
    ("rc", "timed_out", "reason", "answer", "expected"),
    [
        (0, False, None, AnswerState("valid", "incomplete"), "incomplete"),
        (0, False, None, AnswerState("valid", "needs_owner"), "needs_owner"),
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
def test_collected_always_names_its_outcome_and_only_a_verified_plan_succeeds(
    rc: int | None, timed_out: bool, reason: str | None, answer: AnswerState, expected: str
) -> None:
    result = report(stored(rc, timed_out, reason, answer))
    assert (result.status, result.reason) == ("collected", expected) and outcome(stored(rc, timed_out, reason, answer)) == expected
    assert not succeeded(result)


@pytest.mark.parametrize(
    ("verdict", "status", "reason", "success"),
    [
        (None, "pending", "verification", False),
        (Verified("c" * 40), "collected", "verified", True),
        (Verified("c" * 40, reused=True), "collected", "reused", True),
        (Rejected("paths"), "collected", "rejected:paths", False),
        (Rejected("nothing_written"), "collected", "rejected:nothing_written", False),
    ],
)
def test_a_planned_or_unchanged_answer_is_collected_only_with_its_verdict(
    verdict: Verdict | None, status: str, reason: str, success: bool
) -> None:
    for answer in (VALID, REUSE):
        staged = stored(0, False, None, answer, verdict)
        result = report(staged)
        assert (result.status, result.reason) == (status, reason) and outcome(staged) == answer.disposition
        assert succeeded(result) is success


def test_only_collected_can_succeed() -> None:
    assert not succeeded(AttemptResult("pending", "verified"))
