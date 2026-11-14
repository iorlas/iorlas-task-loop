"""The plan artifact's Read list contract and persisted rejection."""

import sqlite3
from pathlib import Path

import pytest
from doubles import FakeSlotFiles, main_at
from git_porcelain import Sha, Tree
from git_porcelain.testing import FakeWorktree
from plan_fixtures import PLAN_TEXT
from test_verifier import KEY, PLAN, UNCHANGED, P, captured, commit, stored, verifier

from taskloop.attempt_types import Checkouts, PlanContentRule, Rejected, Rule, StepRules, Verified
from taskloop.steps import PLAN as STEP


@pytest.mark.parametrize("text", [
    "# Plan\n", "## Read List\n- src/a.py:1-2\n", "## Read list\n", "## Read list\n\n## Work\n- other\n",
    "Mention ## Read list\n- src/a.py:1-2\n", "```md\n## Read list\n- src/a.py:1-2\n```\n",
    "~~~\n## Read list\n- src/a.py:1-2\n~~~\n", "## Read list\n- \n", "## Read list\nProse\n- entry\n",
    "## Read list\n```\n- entry\n```\n", "    ## Read list\n- entry\n",
])
def test_missing_structural_read_list_rejects_artifact(text: str) -> None:
    tree = Tree(Sha("a" * 40), lambda: {P: ("100644", Sha("b" * 40))}, lambda _path: text.encode())
    assert STEP.artifact(tree, STEP.rules("tl-1")) == Rejected(PlanContentRule.READ_LIST)


@pytest.mark.parametrize("text", [
    PLAN_TEXT, "## Read list\n\n* entry\n", "## Read list\n+ entry\n",
    "```\n## Read list\n```\n## Read list\n- entry\n",
    "## Read list\n" + "- entry\n" * 26,  # The entry count and semantic content remain prompt guidance.
])
def test_structural_read_list_accepts_artifact(text: str) -> None:
    tree = Tree(Sha("a" * 40), lambda: {P: ("100644", Sha("b" * 40))}, lambda _path: text.encode())
    assert STEP.artifact(tree, STEP.rules("tl-1")) == "b" * 40


@pytest.mark.parametrize(("data", "rule"), [(b"\xff", "plan_encoding"), (b" \n", "plan_empty"), (b"x" * 11, "plan_size")])
def test_existing_content_failures_keep_precedence(data: bytes, rule: Rule) -> None:
    tree = Tree(Sha("a" * 40), lambda: {P: ("100644", Sha("b" * 40))}, lambda _path: data)
    assert STEP.artifact(tree, StepRules("docs/design/tl-1/", file_cap=10)) == Rejected(rule)


@pytest.mark.parametrize("disposition", ["planned", "unchanged", "replanned"])
def test_new_and_reused_plans_are_checked_and_replanning_succeeds(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts,
    slot_files: FakeSlotFiles, disposition: str,
) -> None:
    commit(slot, {P: "# Old plan\n"})
    main_at(slot)
    answer = UNCHANGED if disposition == "unchanged" else PLAN
    written = {} if disposition == "unchanged" else {P: PLAN_TEXT if disposition == "replanned" else "# New plan\n"}
    captured(registered, tmp_path, slot, checkouts, slot_files, written, answer)
    check = verifier(registered, checkouts, slot_files)
    result = check.verify(KEY)
    if disposition == "replanned":
        assert isinstance(result, Verified)
    else:
        assert result == Rejected(PlanContentRule.READ_LIST)
        assert stored(registered)[0][1] == PlanContentRule.READ_LIST.value
        again = check.verify(KEY)
        assert isinstance(again, Rejected) and again.reason is PlanContentRule.READ_LIST
