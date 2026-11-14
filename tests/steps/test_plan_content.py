"""Plan completion enforces lean artifacts for both new commits and reuse."""

import sqlite3
from pathlib import Path

import pytest
from doubles import FakeSlotFiles, origin_main_at
from git_porcelain import Sha, Tree
from git_porcelain.testing import FakeWorktree
from plan_fixtures import CHANGE_MAP, HEADER, PLAN_TEXT
from test_verifier import KEY, PLAN, UNCHANGED, P, captured, commit, stored, verifier

from taskloop.attempt_loads import verdict_of
from taskloop.attempt_types import Checkouts, PlanContentRule, Rejected, Rule, StepRules, Verified
from taskloop.hold_cause import cause
from taskloop.steps import PLAN as STEP


def artifact(data: bytes, rules: StepRules | None = None) -> Rejected | str | None:
    tree = Tree(Sha("a" * 40), lambda: {P: ("100644", Sha("b" * 40))}, lambda _path: data)
    return STEP.artifact(tree, rules or STEP.rules("tl-1"))


@pytest.mark.parametrize("text", [
    "# Plan\n", "## Change Map\n- src/a.py\n", "## Change map\n", "## Change map\n\n## Work\n- other\n",
    "Mention ## Change map\n- src/a.py\n", "```md\n## Change map\n- src/a.py\n```\n",
    "~~~\n## Change map\n- src/a.py\n~~~\n", "## Change map\n- \n", "## Change map\nProse\n- entry\n",
    "## Change map\n```\n- entry\n```\n", "    ## Change map\n- entry\n",
])
def test_missing_structural_change_map_rejects_artifact(text: str) -> None:
    assert artifact((HEADER + text).encode()) == Rejected(PlanContentRule.CHANGE_MAP)


@pytest.mark.parametrize("text", [
    PLAN_TEXT, HEADER + "## Change map\n\n* entry\n", HEADER + "## Change map\n+ entry\n",
    HEADER + "```\n## Change map\n```\n## Change map\n- entry\n",
    HEADER + "## Change map\n" + "- entry\n" * 26,
])
def test_structural_change_map_accepts_artifact(text: str) -> None:
    assert artifact(text.encode()) == "b" * 40


@pytest.mark.parametrize(("data", "rule"), [(b"\xff", "plan_encoding"), (b" \n", "plan_empty"), (b"x" * 11, "plan_size")])
def test_existing_content_failures_keep_precedence(data: bytes, rule: Rule) -> None:
    assert artifact(data, StepRules("docs/design/tl-1/", file_cap=10)) == Rejected(rule)


@pytest.mark.parametrize("depth", ["", "Depth: unknown\n", "Depth: Small\n", "Depth: small\nDepth: small\n",
                                   "Depth: small\nDepth: large\n", "Depth: small; reason\ndepth: large\n",
                                   "```\nDepth: small\n```\n"])
def test_missing_duplicate_unknown_or_fenced_depth_refuses_completion(depth: str) -> None:
    assert artifact(("# Header\n" + depth + CHANGE_MAP).encode()) == Rejected(PlanContentRule.DEPTH)


@pytest.mark.parametrize("heading", [
    "# As built", "## AS BUILT ###", "### Status: implemented", "## status", "###### Progress",
    "## Implementation progress", "As built\n========", "STATUS: implemented\n---", "Progress\n=======",
    "   ## Implementation Progress ###", "Implementation progress\n---",
])
def test_forbidden_heading_variants_refuse_completion(heading: str) -> None:
    assert artifact((PLAN_TEXT + heading + "\n").encode()) == Rejected(PlanContentRule.HEADING)


@pytest.mark.parametrize("text", [
    "The status stays in the tracker; implementation progress is discussed there.\n",
    "As built is ordinary prose here.\n", "####### Status\n", "    ## Status\n",
    "```markdown\n## Status: implemented\nDepth: large\nAs built\n---\n```\n",
    "~~~~\n## Progress\n```\nDepth: large\n~~~~\n", "````\n## As built\n```\nDepth: large\n````\n",
])
def test_prose_and_fenced_examples_are_allowed(text: str) -> None:
    assert artifact((PLAN_TEXT + text).encode()) == "b" * 40


@pytest.mark.parametrize(("depth", "cap"), [("small", 4_000), ("medium", 8_000), ("large", 12_000)])
@pytest.mark.parametrize("excess", [0, 1])
@pytest.mark.parametrize("reuse", [False, True])
@pytest.mark.parametrize("multibyte", [False, True])
def test_exact_depth_byte_caps_apply_to_new_and_reused_plans(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts,
    slot_files: FakeSlotFiles, depth: str, cap: int, excess: int, reuse: bool, multibyte: bool,
) -> None:
    data = PLAN_TEXT.replace("Depth: small;", f"Depth: {depth};").encode()
    if multibyte:
        data += "é".encode() * ((cap - len(data)) // 2)
    data += b"x" * (cap + excess - len(data))
    assert len(data) == cap + excess
    if reuse:
        commit(slot, {P: data})
        origin_main_at(slot)
    captured(registered, tmp_path, slot, checkouts, slot_files, {} if reuse else {P: data}, UNCHANGED if reuse else PLAN)
    check = verifier(registered, checkouts, slot_files)
    result = check.verify(KEY)
    if excess:
        assert result == Rejected("plan_size")
        assert stored(registered)[0][1] == "plan_size"
    else:
        assert isinstance(result, Verified) and result.reused is reuse
    assert check.verify(KEY) == result


@pytest.mark.parametrize(("text", "rule"), [
    ("# Old plan\n" + CHANGE_MAP, PlanContentRule.DEPTH),
    (HEADER + "## Status: implemented\n" + CHANGE_MAP, PlanContentRule.HEADING),
    (HEADER, PlanContentRule.CHANGE_MAP),
])
@pytest.mark.parametrize("reuse", [False, True])
def test_format_refusals_survive_storage_for_both_commit_and_reuse(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts,
    slot_files: FakeSlotFiles, text: str, rule: PlanContentRule, reuse: bool,
) -> None:
    if reuse:
        commit(slot, {P: text})
        origin_main_at(slot)
    captured(registered, tmp_path, slot, checkouts, slot_files, {} if reuse else {P: text}, UNCHANGED if reuse else PLAN)
    check = verifier(registered, checkouts, slot_files)
    assert check.verify(KEY) == Rejected(rule)
    assert stored(registered)[0][1] == rule.value
    again = check.verify(KEY)
    assert isinstance(again, Rejected) and again.reason is rule


@pytest.mark.parametrize("rule", [*PlanContentRule, "plan_size"])
def test_every_content_refusal_has_words_and_removal_or_repair_advice(rule: Rule) -> None:
    assert verdict_of(("rejected", str(rule), None, 0)) == Rejected(rule)
    explanation = cause("rejected:" + str(rule))
    assert explanation is not None and explanation.fix
    assert str(rule) not in explanation.what + explanation.fix


def test_a_revised_old_plan_can_complete_with_the_new_template(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles,
) -> None:
    commit(slot, {P: "# Old plan\n"})
    origin_main_at(slot)
    captured(registered, tmp_path, slot, checkouts, slot_files, {P: PLAN_TEXT}, PLAN)
    assert isinstance(verifier(registered, checkouts, slot_files).verify(KEY), Verified)


def test_inline_depth_is_refused_with_the_one_line_form_and_own_line_passes() -> None:
    inline = "# Header\ntl-1; base X. Depth: small; one behaviour\n" + CHANGE_MAP
    assert artifact(inline.encode()) == Rejected(PlanContentRule.DEPTH)
    explanation = cause("rejected:" + str(PlanContentRule.DEPTH))
    assert explanation is not None
    fix = explanation.fix or ""
    assert "`Depth: small`" in fix and "not inside a sentence" in fix
    assert artifact(("# Header\ntl-1; base X.\nDepth: small; one behaviour\n" + CHANGE_MAP).encode()) == "b" * 40
