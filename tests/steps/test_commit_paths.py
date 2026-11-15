"""Unchanged answer paths and actionable per-path commit refusals through the owning ports."""

import json
from collections.abc import Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Literal

import pytest
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain import Dirty, GitUnavailable, Recorded, Tree
from git_porcelain.testing import FakeRepo, FakeWorktree

from taskloop import implement_step, plan_step, step_text
from taskloop.agents.settings import AgentSetting
from taskloop.attempt_types import (
    Admission,
    AnswerState,
    AttemptKey,
    CommitWaiting,
    CommitWaitingReason,
    FileRef,
    FileStat,
    PathExplanation,
    Rejected,
    Unsettled,
)
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_commit import Committed, leftovers, settle
from taskloop.ids import NativeIds
from taskloop.operation_evidence import OperationKind, OperationState
from taskloop.operations import commit_failure
from taskloop.prepare import task_branch
from taskloop.repo import RepoId
from taskloop.step import Step
from taskloop.task import TaskReference, TaskScope

FIXTURE = b"-----BEGIN " + b"OPENSSH PRIVATE " + b"KEY-----\n" + b'{"access_' + b'token":"a","refresh_' + b'token":"r"}'


@pytest.fixture
def admission(slot: FakeWorktree) -> Admission:
    slot.checkout_new(task_branch("tl-1"))
    return Admission(AttemptKey("attempt", "dispatch", 1), TaskReference(TaskScope("tasks"), "tl-1"),
                     RepoId(slot.repo.identity().key), "s1", str(slot.path), FileRef("input", "digest"), AgentSetting(),
                     100, (7, "start", "boot"), 1, Step.IMPLEMENT)


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


@pytest.mark.parametrize("broken_evidence", [False, True])
def test_commit_retry_measures_staging_through_record_and_suppresses_adoption(
    tmp_path: Path, admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews,
    monkeypatch: pytest.MonkeyPatch, broken_evidence: bool,
) -> None:
    base = record(slot)
    slot.write_file("edit.txt", "changed")
    files, now = EvidenceFiles(tmp_path / "artifacts"), [0.0]
    timing = partial(files.observe_operation, clock=lambda: now[0], wall=lambda: 100.0, ids=NativeIds())
    original, record_original = FakeWorktree.stage, FakeWorktree.record

    def stage(self: FakeWorktree, paths: Sequence[str], *, literal: bool = True) -> None:
        if not broken_evidence:
            assert any(sample.state is OperationState.ACTIVE for sample in files.operations(admission.key))
        now[0] += 3
        original(self, paths, literal=literal)

    def recording(self: FakeWorktree, message: str, *, paths: Literal["staged"], hooks: bool) -> Recorded:
        now[0] += 2
        result = record_original(self, message, paths=paths, hooks=hooks)
        assert isinstance(result, Recorded)
        return result

    def broken(*_args: object) -> None:
        raise OSError("Evidence unavailable")

    monkeypatch.setattr(FakeWorktree, "stage", stage)
    monkeypatch.setattr(FakeWorktree, "record", recording)
    if broken_evidence:
        monkeypatch.setattr(files, "write_operation", broken)
    quiet_calls = []

    def quiet() -> CommitWaiting | None:
        quiet_calls.append(True)
        return CommitWaiting(CommitWaitingReason.WORKER_ALIVE) if len(quiet_calls) == 2 else None

    result = settle(checkouts, slot_files, admission, base, answer("edit.txt"), quiet, timing)
    assert result == CommitWaiting(CommitWaitingReason.WORKER_ALIVE)
    assert head(slot) == base and len(quiet_calls) == 2
    made = settle(checkouts, slot_files, admission, base, answer("edit.txt"), lambda: None, timing)
    assert isinstance(made, Committed) and made.sha != base
    assert settle(checkouts, slot_files, admission, base, answer("edit.txt"), lambda: None, timing) == made
    samples = files.operations(admission.key)
    if broken_evidence:
        assert samples == ()
    else:
        assert len(samples) == 2 and all(sample.kind is OperationKind.COMMIT for sample in samples)
        assert {(sample.state, sample.elapsed) for sample in samples} == {
            (OperationState.FAILED, 3.0), (OperationState.COMPLETED, 5.0),
        }


@pytest.mark.parametrize("saved", [False, True])
def test_keep_only_measures_saved_work_review(
    tmp_path: Path, admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews, saved: bool,
) -> None:
    message = "Saved\n\nTask-Loop-Wip: preserved" if saved else "Baseline"
    made = slot.record(message, paths="all", allow_empty=True)
    assert isinstance(made, Recorded)
    files = EvidenceFiles(tmp_path / "artifacts")
    timing = partial(files.observe_operation, clock=lambda: 1.0, wall=lambda: 100.0, ids=NativeIds())
    kept = AnswerState("valid", "unchanged", "keep")
    result = settle(checkouts, slot_files, admission, made.sha, kept, lambda: None, timing)
    assert isinstance(result, Committed) and (result.sha != made.sha) == saved
    assert len(files.operations(admission.key)) == int(saved)
    assert all(sample.state is OperationState.COMPLETED for sample in files.operations(admission.key))


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
    found = settle(checkouts, slot_files, admission, base, answer("unrelated.txt"), lambda: None)
    assert isinstance(found, Unsettled) and found.reason == "unsafe"
    assert found.explanations == (PathExplanation(path, "The file content matches a credential signature (private key or login tokens)."),)
    assert stages == [] and head(slot) == base
    assert leftovers(checkouts, slot_files, admission, base, answer("unrelated.txt"), None) == found


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
    for each in (path, linked, "scratch.txt", "src/.gitattributes", "listed.txt"):
        slot.write_file(each, "new data")
    slot_files.entries[slot.path / path] = stat
    if unreadable:
        slot_files.unreadable.add(slot.path / path)
    slot_files.entries[slot.path / "linked"] = ancestor_stat
    found = settle(checkouts, slot_files, admission, base, answer("listed.txt"), lambda: None)
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
            if step is plan_step:
                assert "leave files you did not change out of paths" in text
            else:
                assert "`paths`" not in text
                assert "Remove unwanted untracked files and restore unwanted tracked edits before answering" in text
            assert "symlink or under one, not a plain file" not in text
    assert words in commit_failure(found).detail


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
    stages: list[tuple[str, ...]], change: str, monkeypatch: pytest.MonkeyPatch,
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
    # The file port's mode/type overrides must also be reflected in the typed Git evidence.
    original = FakeWorktree.dirty

    def dirty(self: FakeWorktree, base: str | None = None, *, ignored_under: Sequence[str] = ()) -> Dirty:
        return replace(original(self, base, ignored_under=ignored_under), tracked=(path,))

    monkeypatch.setattr(FakeWorktree, "dirty", dirty)
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
    assert isinstance(found, Unsettled) and any(expected in each.explanation for each in found.explanations)


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
    slot.write_file("docs/design/tl-1/unlisted.txt", "unlisted plan change")
    slot.write_file("outside.txt", "unlisted outside change")
    declared = replace(answer(path, "docs/design/tl-1/note.md"), disposition="planned")
    result = settle(checkouts, slot_files, replace(admission, step=Step.PLAN), base, declared, lambda: None)
    assert isinstance(result, Committed) and stages == [("docs/design/tl-1/note.md",)]


def test_implement_commits_all_slot_changes_with_the_answer_message_and_attempt_trailer(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews, stages: list[tuple[str, ...]],
) -> None:
    for path in ("edit.txt", "delete.txt", "old-name.txt", "unchanged.txt"):
        slot.write_file(path, "original")
    base = record(slot)
    slot.write_file("edit.txt", "changed")
    slot.remove_file("delete.txt")
    slot.remove_file("old-name.txt")
    slot.write_file("new-name.txt", "original")
    slot.write_file("added.txt", "added")
    declared = answer("edit.txt", "unchanged.txt")
    assert leftovers(checkouts, slot_files, admission, base, declared, None) is None
    result = settle(checkouts, slot_files, admission, base, declared, lambda: None)
    assert isinstance(result, Committed)
    assert stages == [("added.txt", "delete.txt", "edit.txt", "new-name.txt", "old-name.txt")]
    assert slot.dirty().raw is False
    commits = slot.repo.history([result.sha], not_on=[base])
    assert len(commits) == 1 and commits[0].subject == "Edit the file" and commits[0].body == "Task-Loop-Attempt: attempt"


@pytest.mark.parametrize(("path", "predicate"), [
    (".Beads/data", "excluded"), ("src/.github/data", "changed Git file"),
    ("docs/PLAN.MD", "cannot change plan.md"), ("line\nbreak.txt", "newline"), ("x" * 256, "255 bytes"),
])
def test_unlisted_forbidden_paths_refuse_before_staging_and_match_preview(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews,
    stages: list[tuple[str, ...]], path: str, predicate: str,
) -> None:
    base = record(slot)
    slot.write_file("edit.txt", "allowed")
    slot.write_file(path, "forbidden")
    found = settle(checkouts, slot_files, admission, base, answer("edit.txt"), lambda: None)
    assert isinstance(found, Unsettled) and found.reason == "unsafe"
    assert any(each.path == path and predicate in each.explanation for each in found.explanations)
    assert leftovers(checkouts, slot_files, admission, base, answer("edit.txt"), None) == found
    assert stages == [] and head(slot) == base


@pytest.mark.parametrize("count", [96, 97])
def test_actual_changed_path_limit_is_applied_without_truncating_the_selection(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews,
    stages: list[tuple[str, ...]], count: int,
) -> None:
    base = record(slot)
    paths = tuple(f"src/file-{index:03}.py" for index in range(count))
    for path in paths:
        slot.write_file(path, "changed")
    declared = answer(paths[0])
    preview = leftovers(checkouts, slot_files, admission, base, declared, None)
    found = settle(checkouts, slot_files, admission, base, declared, lambda: None)
    if count == 96:
        assert preview is None and isinstance(found, Committed) and stages == [paths]
        assert slot.dirty().raw is False
    else:
        assert preview == found and isinstance(found, Unsettled) and found.reason == "unsafe"
        assert found.explanations == (PathExplanation(paths[0], "The slot has 97 changed paths; the limit is 96 paths."),)
        assert stages == [] and head(slot) == base


def test_ignored_attributes_for_an_unlisted_change_refuse_and_match_preview(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews, stages: list[tuple[str, ...]],
) -> None:
    slot.write_file(".gitignore", "nested/.gitattributes\n")
    base = record(slot)
    slot.write_file("edit.txt", "listed")
    slot.write_file("nested/file.py", "unlisted")
    slot.write_file("nested/.gitattributes", "*.py filter=custom\n")
    declared = answer("edit.txt")
    expected = Unsettled("ignored", ("nested/.gitattributes",))
    assert leftovers(checkouts, slot_files, admission, base, declared, None) == expected
    assert settle(checkouts, slot_files, admission, base, declared, lambda: None) == expected
    assert stages == [] and head(slot) == base


def test_a_foreign_index_entry_with_no_worktree_changes_still_refuses(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews, stages: list[tuple[str, ...]],
) -> None:
    slot.write_file("file.txt", "original")
    base = record(slot)
    slot.write_file("file.txt", "foreign staged edit")
    slot.stage(("file.txt",))
    slot.write_file("file.txt", "original")
    stages.clear()
    assert settle(checkouts, slot_files, admission, base, answer("file.txt"), lambda: None) == Unsettled("staged", ("file.txt",))
    assert stages == [] and head(slot) == base


def test_unknown_dirty_evidence_propagates_without_staging(
    admission: Admission, slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews,
    stages: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = record(slot)
    original = FakeWorktree.dirty

    def dirty(self: FakeWorktree, base: str | None = None, *, ignored_under: Sequence[str] = ()) -> Dirty:
        if base is not None:
            raise GitUnavailable("unreadable typed status")
        return original(self, base, ignored_under=ignored_under)

    monkeypatch.setattr(FakeWorktree, "dirty", dirty)
    with pytest.raises(GitUnavailable, match="unreadable typed status"):
        settle(checkouts, slot_files, admission, base, answer("edit.txt"), lambda: None)
    assert stages == [] and head(slot) == base
