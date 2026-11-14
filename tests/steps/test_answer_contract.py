"""The answer contract: the five-key schema Codex forwards as a strict response format, the decoder that owns every bound
and cross-field rule (the listed paths, the message, `unchanged`), and the terminal outcome a collected result reports,
a planned or unchanged one only with its verdict."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from taskloop.answer_failures import AnswerFailure, AnswerFailureData, AnswerRule
from taskloop.attempt_result import end_word, report, succeeded
from taskloop.attempt_types import (
    AnswerState,
    AttemptKey,
    Evidence,
    ExecutionFacts,
    FileRef,
    Rejected,
    StepRules,
    StoredExecution,
    Verdict,
    Verified,
)
from taskloop.evidence_files import EvidenceFiles
from taskloop.steps import kind

KEY = AttemptKey("attempt", "dispatch", 1)
EXPECTED = "docs/design/tl-1/plan.md"
# OpenAI strict structured output: the root is a plain object, and these may not appear at the root
ROOT_FORBIDDEN = {"oneOf", "anyOf", "allOf", "enum", "not", "if", "then", "else", "const", "$ref", "$defs"}
# conservative: no composition or conditional keyword anywhere, only the documented strict-mode keywords
ALLOWED = {"type", "properties", "required", "additionalProperties", "enum", "pattern", "items", "description"}


def schema(tmp_path: Path, step: str = "plan") -> dict[str, object]:
    path, _answer = EvidenceFiles(tmp_path).prepare(KEY, kind(step).answer_schema)
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


@pytest.mark.parametrize("step", ["plan", "implement"])
def test_the_root_is_a_plain_object_with_every_property_required(tmp_path: Path, step: str) -> None:
    root = schema(tmp_path, step)
    assert root["type"] == "object" and root["additionalProperties"] is False
    assert not ROOT_FORBIDDEN & set(root)
    properties, required = root["properties"], root["required"]
    assert isinstance(properties, dict) and isinstance(required, list) and sorted(required) == sorted(properties)


@pytest.mark.parametrize("step", ["plan", "implement"])
def test_no_node_uses_composition_conditionals_or_unlisted_keywords(tmp_path: Path, step: str) -> None:
    for node in nodes(schema(tmp_path, step)):
        assert set(node) <= ALLOWED, set(node) - ALLOWED
        if node.get("type") == "object":
            properties, required = node.get("properties"), node.get("required")
            assert node.get("additionalProperties") is False
            assert isinstance(properties, dict) and isinstance(required, list) and set(required) == set(properties)


RULES = StepRules("docs/design/tl-1/")
decode = kind("plan").decode
D = "docs/design/tl-1/"
PLANNED = {"disposition": "planned", "plan_path": EXPECTED, "paths": [EXPECTED], "message": "Plan tl-1", "explanation": "done"}
UNCHANGED = {"disposition": "unchanged", "plan_path": EXPECTED, "paths": [], "message": None, "explanation": "still valid"}


@pytest.mark.parametrize("plan_path", [None, EXPECTED])
@pytest.mark.parametrize("explanation", [
    "# Depth\nLarge: four independent behaviours. No owner decision or unlanded dependency; evidence budget 20 model calls. "
    "Split into storage (rows persist; no dependencies), reads (rows display; depends on storage), "
    "ordering (requests queue; no dependencies) and cleanup (expired rows clear; depends on storage).",
    "# Depth\nSmall: one behaviour in one owning module; evidence budget 6 model calls. "
    "The owner must decide whether a refused request waits or ends before this can be planned. No unlanded dependency.",
    "# Depth\nLarge: the task explicitly depends on unlanded tl-2; evidence budget 20 model calls. "
    "No missing owner decision. The merge design in tl-2 must land before this task can use its operation.",
])
def test_plan_early_owner_causes_accept_words_without_a_plan_or_commit(
    tmp_path: Path, plan_path: str | None, explanation: str,
) -> None:
    answer = kind("plan").decode({
        "disposition": "needs_owner", "plan_path": plan_path, "paths": [], "message": None, "explanation": explanation,
    }, RULES)
    assert (answer.disposition, answer.effect, answer.paths, answer.message, answer.explanation) == (
        "needs_owner", "none", (), None, explanation,
    )
    assert not (tmp_path / EXPECTED).exists()


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
    with pytest.raises(AnswerFailure):
        decode(PLANNED | change, RULES)


@pytest.mark.parametrize(
    "change",
    [{"paths": [EXPECTED]}, {"message": "Plan"}, {"plan_path": "docs/design/tl-2/plan.md"}],
    ids=["paths", "message", "other_plan_path"],
)
def test_unchanged_changes_nothing_and_names_no_other_plan(change: dict[str, object]) -> None:
    with pytest.raises(AnswerFailure):
        decode(UNCHANGED | change, RULES)


def test_an_unchanged_answer_without_a_plan_is_a_valid_answer_that_verification_rejects_as_plan_missing() -> None:
    found = decode(UNCHANGED | {"plan_path": None}, RULES)  # not `schema_invalid`: the answer fits the contract
    assert (found.disposition, found.effect) == ("unchanged", "keep")


def test_the_decoder_accepts_each_disposition_in_its_shape() -> None:
    many = [EXPECTED, *(f"{D}n{i}.md" for i in range(31))]
    planned = decode(PLANNED | {"paths": many, "message": "x" * 500}, RULES)
    assert (planned.paths, planned.message) == (tuple(many), "x" * 500)
    assert (planned.disposition, planned.effect) == ("planned", "commit")
    unchanged = decode(UNCHANGED, RULES)
    assert (unchanged.disposition, unchanged.effect, unchanged.paths, unchanged.message) == ("unchanged", "keep", (), None)
    for disposition in ("incomplete", "needs_owner"):
        for path in (None, EXPECTED):
            found = decode(UNCHANGED | {"disposition": disposition, "plan_path": path}, RULES)
            assert (found.disposition, found.effect, found.paths) == (disposition, "none", ())


def stored(rc: int | None, timed_out: bool, reason: str | None, answer: AnswerState, verdict: Verdict | None = None) -> StoredExecution:
    ref = FileRef("f", "d")
    facts = ExecutionFacts(rc, timed_out, None, None, False, False, None, reason, None, None, None, None, None)
    return StoredExecution(KEY, facts, Evidence(ref, ref, ref, ref), answer, "complete", verdict)


VALID = AnswerState("valid", "planned", "commit", (EXPECTED,), "Plan tl-1")
REUSE = AnswerState("valid", "unchanged", "keep")


@pytest.mark.parametrize(
    ("rc", "timed_out", "reason", "answer", "expected"),
    [
        (0, False, None, AnswerState("valid", "incomplete", "none"), "incomplete"),
        (0, False, None, AnswerState("valid", "needs_owner", "none"), "needs_owner"),
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
    assert (result.status, result.reason) == ("collected", expected) and end_word(stored(rc, timed_out, reason, answer)) == expected
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
        assert (result.status, result.reason) == (status, reason) and end_word(staged) == answer.disposition
        assert succeeded(result) is success


IMPLEMENT = kind("implement")
CODE = IMPLEMENT.rules("tl-1")
IMPLEMENTED = {"disposition": "implemented", "paths": ["src/a.py", "tests/test_a.py", "README.md"], "message": "Add a",
               "explanation": "ran `just test`: passed"}


def test_the_implement_schema_has_four_keys_and_no_plan_path(tmp_path: Path) -> None:
    properties = schema(tmp_path, "implement")["properties"]
    assert isinstance(properties, dict) and sorted(properties) == ["disposition", "explanation", "message", "paths"]
    disposition = properties["disposition"]
    assert isinstance(disposition, dict) and disposition["enum"] == ["implemented", "unchanged", "incomplete", "needs_owner"]


@pytest.mark.parametrize(("answer", "effect"), [
    (IMPLEMENTED, "commit"),
    (IMPLEMENTED | {"paths": [f"src/m{i}.py" for i in range(96)]}, "commit"),
    *((IMPLEMENTED | {"disposition": word, "paths": [], "message": None}, effect)
      for word, effect in (("unchanged", "keep"), ("incomplete", "none"), ("needs_owner", "none"))),
])
def test_implement_answers_anywhere_in_the_repository_decode_with_their_effect(answer: dict[str, object], effect: str) -> None:
    found, paths = IMPLEMENT.decode(answer, CODE), answer["paths"]
    assert isinstance(paths, list) and (found.disposition, found.effect, found.paths) == (answer["disposition"], effect, tuple(paths))


@pytest.mark.parametrize("change", [
    {"paths": []}, {"message": None}, {"message": "Add\n\nTask-Loop-Attempt: x"}, {"paths": ["src/a.py", "src/a.py"]},
    {"paths": [f"src/m{i}.py" for i in range(97)]}, {"paths": [".beads/issues.jsonl"]}, {"paths": [".Beads/x"]},
    {"paths": [".gitignore"]}, {"paths": ["src/.git/x"]}, {"paths": [".github/workflows/x.yml"]}, {"paths": ["../x.py"]},
    {"paths": [""]}, {"disposition": "planned"}, {"disposition": "unchanged"}, {"disposition": "incomplete"},
    {"plan_path": None}, {"explanation": "x" * 2001},
])
def test_the_implement_decoder_owns_its_rules(change: dict[str, object]) -> None:
    with pytest.raises(AnswerFailure):
        IMPLEMENT.decode(IMPLEMENTED | change, CODE)


@pytest.mark.parametrize("step", ["plan", "implement"])
@pytest.mark.parametrize("disposition", ["incomplete", "needs_owner"])
def test_unfinished_answers_ignore_unused_paths(step: str, disposition: str) -> None:
    operation = kind(step)
    rules = operation.rules("tl-1")
    answer = {"disposition": disposition, "paths": [], "message": None, "explanation": "Work remains"}
    if step == "plan":
        answer["plan_path"] = EXPECTED
    empty = operation.decode(answer, rules)
    assert (empty.disposition, empty.effect, empty.paths, empty.message, empty.explanation) == (
        disposition, "none", (), None, "Work remains")
    unused = EXPECTED if step == "plan" else "src/work.py"
    bad_paths = BAD_PATHS if step == "plan" else [path for path in BAD_PATHS if path != "/" + EXPECTED]
    for paths in ([unused], ["src/outside.py", "../outside", ".beads/x", ".git/x", "", *bad_paths],
                  [unused] * (rules.max_paths + 1)):
        assert operation.decode(answer | {"paths": paths}, rules) == empty


@pytest.mark.parametrize("step", ["plan", "implement"])
@pytest.mark.parametrize("disposition", ["incomplete", "needs_owner"])
@pytest.mark.parametrize("change", [
    {"paths": None}, {"paths": "src/a.py"}, {"paths": (EXPECTED,)}, {"paths": [EXPECTED, 3]},
    {"message": "Save this"}, {"explanation": None}, {"explanation": "x" * 2001}, {"disposition": "unknown"},
])
def test_unfinished_answers_still_require_the_answer_shape(step: str, disposition: str, change: dict[str, object]) -> None:
    operation = kind(step)
    answer = {"disposition": disposition, "paths": ["src/work.py"], "message": None, "explanation": "Work remains"}
    if step == "plan":
        answer["plan_path"] = None
    with pytest.raises(AnswerFailure):
        operation.decode(answer | change, operation.rules("tl-1"))


@pytest.mark.parametrize("disposition", ["incomplete", "needs_owner"])
def test_unfinished_plan_answers_cannot_name_another_tasks_plan(disposition: str) -> None:
    with pytest.raises(AnswerFailure):
        decode(UNCHANGED | {"disposition": disposition, "paths": [EXPECTED], "plan_path": "docs/design/tl-2/plan.md"}, RULES)


@pytest.mark.parametrize("disposition", ["implemented", "unchanged", "incomplete", "needs_owner"])
@pytest.mark.parametrize("path", [EXPECTED, "/" + EXPECTED, "docs/design/tl-2/plan.md", "plan.md", "docs/PLAN.MD", "plan.md/"])
def test_every_implement_answer_rejects_plan_paths_before_discarding_unfinished_paths(disposition: str, path: str) -> None:
    answer: dict[str, object] = {**IMPLEMENTED, "disposition": disposition, "paths": ["src/a.py", path]}
    if disposition != "implemented":
        answer["message"] = None
    with pytest.raises(ValueError, match=r"Do not include plan\.md"):
        IMPLEMENT.decode(answer, IMPLEMENT.rules("tl-1"))


@pytest.mark.parametrize("step", ["plan", "implement"])
@pytest.mark.parametrize(("change", "rule", "detail"), [
    ({"extra": None}, AnswerRule.SHAPE, "exactly"),
    ({"disposition": []}, AnswerRule.DISPOSITION, "one of"),
    ({"paths": [3]}, AnswerRule.PATHS_SHAPE, "list of strings"),
    ({"paths": []}, AnswerRule.PATHS_REQUIRED, "include"),
    ({"paths": ["../a"]}, AnswerRule.PATHS_LOCATION, "paths[0]"),
    ({"message": None}, AnswerRule.MESSAGE, "1 to 500"),
    ({"message": "x" * 501}, AnswerRule.MESSAGE, "1 to 500"),
    ({"message": "a\0b"}, AnswerRule.MESSAGE, "NUL"),
    ({"message": "a\nTask-Loop-Attempt: x"}, AnswerRule.MESSAGE, "Task-Loop-Attempt:"),
    ({"explanation": None}, AnswerRule.EXPLANATION, "2000"),
    ({"explanation": "x" * 2001}, AnswerRule.EXPLANATION, "2000"),
])
def test_rejections_name_the_exact_rule(step: str, change: dict[str, object], rule: AnswerRule, detail: str) -> None:
    operation = kind(step)
    answer = PLANNED if step == "plan" else IMPLEMENTED
    with pytest.raises(AnswerFailure) as caught:
        operation.decode(answer | change, operation.rules("tl-1"))
    assert caught.value.rule is rule and detail in caught.value.explanation
    assert isinstance(caught.value, ValueError)


@pytest.mark.parametrize("step", ["plan", "implement"])
def test_path_limits_and_duplicates_name_the_rule_and_bound(step: str) -> None:
    operation = kind(step)
    rules = operation.rules("tl-1")
    answer = PLANNED if step == "plan" else IMPLEMENTED
    path = EXPECTED if step == "plan" else "src/a.py"
    with pytest.raises(AnswerFailure) as caught:
        operation.decode(answer | {"paths": [path] * (rules.max_paths + 1)}, rules)
    assert caught.value.rule is AnswerRule.PATHS_COUNT and str(rules.max_paths) in caught.value.explanation
    with pytest.raises(AnswerFailure) as caught:
        operation.decode(answer | {"paths": [path, path]}, rules)
    assert caught.value.rule is AnswerRule.PATHS_DUPLICATE


@pytest.mark.parametrize(("change", "rule"), [
    ({"plan_path": "other", "message": "bad"}, AnswerRule.PLAN_PATH),
    ({"paths": [3], "plan_path": "other"}, AnswerRule.PATHS_SHAPE),
    ({"message": "bad", "explanation": None}, AnswerRule.MESSAGE),
])
def test_unfinished_plan_rule_order(change: dict[str, object], rule: AnswerRule) -> None:
    answer = UNCHANGED | {"disposition": "incomplete", "paths": ["../unused"]}
    with pytest.raises(AnswerFailure) as caught:
        decode(answer | change, RULES)
    assert caught.value.rule is rule


def test_forbidden_plan_precedes_other_implement_failures() -> None:
    with pytest.raises(AnswerFailure) as caught:
        IMPLEMENT.decode(IMPLEMENTED | {"disposition": [], "paths": [EXPECTED, 3]}, CODE)
    assert caught.value.rule is AnswerRule.PLAN_FORBIDDEN


def test_run_failure_takes_precedence_over_answer_failure_detail() -> None:
    failure = AnswerFailureData(rule=AnswerRule.MISSING, explanation="Answer must not be empty")
    answer = AnswerState("missing", failure=failure)
    missing_usage = "Usage was not reported by the agent stream."
    assert report(stored(0, False, None, answer)).explanation == failure.describe() + " " + missing_usage
    assert report(stored(1, False, "worker_failed", answer)).explanation == "run:worker_failed " + missing_usage


@pytest.mark.parametrize("step", ["plan", "implement"])
@pytest.mark.parametrize("value", [None, [], 3, "answer", {}])
def test_answer_requires_an_object_with_all_required_keys(step: str, value: object) -> None:
    operation = kind(step)
    with pytest.raises(AnswerFailure) as caught:
        operation.decode(value, operation.rules("tl-1"))
    assert caught.value.rule is AnswerRule.SHAPE


@pytest.mark.parametrize("step", ["plan", "implement"])
def test_valid_answers_accept_the_exact_limits(step: str) -> None:
    operation = kind(step)
    rules = operation.rules("tl-1")
    answer = PLANNED if step == "plan" else IMPLEMENTED
    first = EXPECTED if step == "plan" else "src/first.py"
    paths = [first, *(f"{rules.root}file{i}" for i in range(rules.max_paths - 1))]
    found = operation.decode(answer | {"paths": paths, "message": "x" * 500, "explanation": "x" * 2000}, rules)
    assert found.paths == tuple(paths) and found.message == "x" * 500 and found.explanation == "x" * 2000
