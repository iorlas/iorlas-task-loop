"""Unchanged answer paths and actionable per-path commit refusals through the owning ports."""

import json
from collections.abc import Sequence
from dataclasses import replace

import pytest
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain import Recorded, Tree
from git_porcelain.testing import FakeRepo, FakeWorktree

from taskloop import implement_step, plan_step, step_text
from taskloop.agents.settings import AgentSetting
from taskloop.attempt_types import Admission, AnswerState, AttemptKey, FileRef, FileStat, PathExplanation, Rejected, Unsettled
from taskloop.factory_commit import Committed, leftovers, settle
from taskloop.operations import verify_failure
from taskloop.prepare import task_branch
from taskloop.repo import RepoId
from taskloop.task import TaskReference, TaskScope

FIXTURE = b"-----BEGIN " + b"OPENSSH PRIVATE " + b"KEY-----\n" + b'{"access_' + b'token":"a","refresh_' + b'token":"r"}'


@pytest.fixture
def admission(slot: FakeWorktree) -> Admission:
    slot.checkout_new(task_branch("tl-1"))
    return Admission(AttemptKey("attempt", "dispatch", 1), TaskReference(TaskScope("tasks"), "tl-1"),
                     RepoId(slot.repo.identity().key), "s1", str(slot.path), FileRef("input", "digest"), AgentSetting(),
                     100, (7, "start", "boot"), 1, "implement")


@pytest.fixture
def stages(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    original = FakeWorktree.stage

    def stage(self: FakeWorktree, paths: Sequence[str], *, literal: bool = True) -> None:
        calls.append(tuple(paths))
        original(self, paths, literal=literal)

    monkeypatch.setattr(FakeWorktree, "stage", stage)
    return calls


def record(slot: FakeWorktree) -> str:
    made = slot.record("Baseline", paths="all", allow_empty=True)
    assert isinstance(made, Recorded)
    return made.sha


def answer(*paths: str) -> AnswerState:
    return AnswerState("valid", "implemented", "commit", paths, "Edit the file")


def head(slot: FakeWorktree) -> str | None:
    return next(info.head for info in slot.repo.worktrees() if info.path == slot.path)


@pytest.mark.parametrize("existing", [False, True])
def test_changed_or_added_credential_fixture_names_the_real_predicate_without_staging(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews,
    stages: list[tuple[str, ...]], existing: bool,
) -> None:
    path = "tests/steps/test_verifier.py"
    slot.write_file(path, "ordinary old source" if existing else b"")
    if not existing:
        slot.remove_file(path)
    base = record(slot)
    slot.write_file(path, FIXTURE)
    found = settle(checkouts, slot_files, admission, base, answer(path), lambda: None)
    assert isinstance(found, Unsettled) and found.reason == "unsafe"
    assert found.explanations == (PathExplanation(path, "The file content matches a credential signature (private key or login tokens)."),)
    assert stages == [] and head(slot) == base
    assert leftovers(checkouts, slot_files, admission, base, answer(path), None) == found


@pytest.mark.parametrize(("stat", "unreadable", "words"), [
    (FileStat("file", 8, True), False, "execute bit"),
    (FileStat("file", (1 << 20) + 1, False), False, "1048576 bytes"),
    (FileStat("file", 8, False), True, "cannot read"),
    (FileStat("link", 8, False), False, "symlink"),
    (FileStat("dir", 8, False), False, "not a plain file"),
    (None, False, "missing"),
])
@pytest.mark.parametrize(("ancestor_stat", "ancestor_words"), [
    (FileStat("link", 8, False), "a symlink"),
    (FileStat("file", 8, False), "not a directory"),
    (None, "missing or unreadable"),
])
def test_multiple_refusals_keep_each_predicate_and_leftovers_in_both_step_prompts(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews,
    stages: list[tuple[str, ...]], stat: FileStat | None, unreadable: bool, words: str,
    ancestor_stat: FileStat | None, ancestor_words: str,
) -> None:
    base = record(slot)
    path, linked = "src/a\x1b.py", "linked/file.py"
    for each in (path, linked, "scratch.txt", "src/.gitattributes"):
        slot.write_file(each, "new data")
    slot_files.entries[slot.path / path] = stat
    if unreadable:
        slot_files.unreadable.add(slot.path / path)
    slot_files.entries[slot.path / "linked"] = ancestor_stat
    found = settle(checkouts, slot_files, admission, base, answer(path, linked), lambda: None)
    assert isinstance(found, Unsettled) and found.reason == "unsafe"
    reasons = {each.path: each.explanation for each in found.explanations}
    assert set(reasons) == {path, linked, "src/.gitattributes"}
    assert words in reasons[path] and f"Ancestor 'linked' is {ancestor_words}" in reasons[linked]
    assert "changed Git file" in reasons["src/.gitattributes"]
    assert all(reasons.values()) and stages == [] and head(slot) == base
    for step in (implement_step, plan_step):
        for unrecorded in (True, False):
            text = step.feedback(found, step.step_rules("tl-1"), 1, "Task", "NONCE", unrecorded=unrecorded)
            assert words in text and "scratch.txt" in text and "Ancestor 'linked'" in text
            assert json.dumps(path) in text and "\x1b" not in text
            assert "leave files you did not change out of paths" in text
            assert "symlink or under one, not a plain file" not in text
    assert words in verify_failure(found).detail


def test_unchanged_credential_ordinary_and_over_cap_files_are_omitted_from_the_commit(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews, stages: list[tuple[str, ...]],
) -> None:
    unchanged = ("tests/fixture.py", "ordinary.txt", "large.txt")
    for path, data in zip(unchanged, (FIXTURE, b"plain", b"x" * ((1 << 20) + 1)), strict=True):
        slot.write_file(path, data)
    slot.write_file("edit.txt", "old")
    base = record(slot)
    slot.write_file("edit.txt", "new")
    declared = answer(*unchanged, "edit.txt")
    assert leftovers(checkouts, slot_files, admission, base, declared, None) is None
    result = settle(checkouts, slot_files, admission, base, declared, lambda: None)
    assert isinstance(result, Committed) and result.sha != base
    assert stages == [("edit.txt",)] and declared.paths == (*unchanged, "edit.txt")
    before, after = slot.repo.tree(base), slot.repo.tree(result.sha)
    assert before is not None and after is not None
    assert {path for path in after.files if after.files[path] != before.files.get(path)} == {"edit.txt"}


def test_all_unchanged_is_nothing_written_without_staging(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews, stages: list[tuple[str, ...]],
) -> None:
    slot.write_file("fixture.py", FIXTURE)
    base = record(slot)
    assert leftovers(checkouts, slot_files, admission, base, answer("fixture.py"), None) is None
    assert settle(checkouts, slot_files, admission, base, answer("fixture.py"), lambda: None) == Rejected("nothing_written")
    assert stages == [] and head(slot) == base


@pytest.mark.parametrize("change", ["execute", "link", "unreadable", "ancestor", "delete"])
def test_unchanged_content_does_not_hide_file_changes_or_unreadability(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews,
    stages: list[tuple[str, ...]], change: str,
) -> None:
    path = "src/file.py"
    slot.write_file(path, "ordinary")
    base = record(slot)
    if change == "delete":
        slot.remove_file(path)
    elif change == "unreadable":
        slot_files.unreadable.add(slot.path / path)
    elif change == "ancestor":
        slot_files.entries[slot.path / "src"] = FileStat("link", 8, False)
    else:
        slot_files.entries[slot.path / path] = FileStat("link" if change == "link" else "file", 8, change == "execute")
    read = leftovers(checkouts, slot_files, admission, base, answer(path), None)
    found = settle(checkouts, slot_files, admission, base, answer(path), lambda: None)
    if change == "delete":
        assert read is None and isinstance(found, Committed) and stages == [(path,)]
        tree = slot.repo.tree(found.sha)
        assert tree is not None and path not in tree.files
    else:
        assert read == found and isinstance(found, Unsettled) and found.reason == "unsafe"
        assert found.explanations[0].explanation and stages == []


@pytest.mark.parametrize(("ancestor", "expected"), [(False, "baseline Git mode is 100755"), (True, "baseline ancestor 'src'")])
def test_baseline_mode_and_type_changes_are_explained(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews,
    ancestor: bool, expected: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "src/file.py"
    slot.write_file("src" if ancestor else path, "old")
    base = record(slot)
    original_tree = FakeRepo.tree

    def tree(self: FakeRepo, rev: str) -> Tree | None:
        found = original_tree(self, rev)
        if found is not None and found.sha == base and not ancestor:
            return Tree(found.sha, lambda: {**found.files, path: ("100755", found.files[path][1])}, found.read)
        return found

    monkeypatch.setattr(FakeRepo, "tree", tree)
    if ancestor:
        slot.remove_file("src")
    slot.write_file(path, "new")
    found = settle(checkouts, slot_files, admission, base, answer(path), lambda: None)
    assert isinstance(found, Unsettled) and expected in found.explanations[0].explanation


def test_empty_explanation_is_invalid() -> None:
    with pytest.raises(ValueError, match="needs an explanation"):
        PathExplanation("file.py", " ")


def test_diagnostic_bounds_keep_the_predicate_after_a_long_escaped_path() -> None:
    path = "src/" + "x" * 230 + "\x1b.py"
    found = Unsettled("unsafe", explanations=tuple(PathExplanation(path + str(n), "The file has an execute bit set.")
                                                 for n in range(96)))
    text = step_text.unsafe_details(found)
    assert json.dumps(path + "0") in text.splitlines()[0]
    assert "execute bit" in text.splitlines()[0] and "\x1b" not in text
    assert len(text.splitlines()) == 51 and text.endswith("+46 more")


def test_omitting_an_unchanged_path_does_not_allow_its_foreign_index_entry(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews, stages: list[tuple[str, ...]],
) -> None:
    slot.write_file("unchanged.txt", "original")
    base = record(slot)
    slot.write_file("unchanged.txt", "someone else's staged edit")
    slot.stage(("unchanged.txt",))
    slot.write_file("unchanged.txt", "original")
    slot.write_file("edit.txt", "our edit")
    stages.clear()
    found = settle(checkouts, slot_files, admission, base, answer("unchanged.txt", "edit.txt"), lambda: None)
    assert isinstance(found, Unsettled) and found.reason == "staged" and found.listing == ("unchanged.txt",)
    assert stages == [("edit.txt",)] and head(slot) == base


def test_unchanged_plan_path_is_filtered_with_the_same_rules(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews, stages: list[tuple[str, ...]],
) -> None:
    path = "docs/design/tl-1/plan.md"
    slot.write_file(path, FIXTURE)
    base = record(slot)
    slot.write_file("docs/design/tl-1/note.md", "new note")
    declared = replace(answer(path, "docs/design/tl-1/note.md"), disposition="planned")
    result = settle(checkouts, slot_files, replace(admission, step="plan"), base, declared, lambda: None)
    assert isinstance(result, Committed) and stages == [("docs/design/tl-1/note.md",)]
