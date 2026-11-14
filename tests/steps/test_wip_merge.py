"""A stopped merge is preserved through the owning save operation, never treated as completed implementation."""

import sqlite3
from dataclasses import replace

import pytest
from git_porcelain import GitUnavailable, MergeStarted, Recorded, UnmergedPaths
from git_porcelain.testing import FakeRepo, FakeWorktree

from taskloop.hold_store import HoldInsert, HoldStore
from taskloop.wip import Refused, SaveReason, Source, is_saved, park, save, saved_since


@pytest.mark.parametrize("merge", [False, True])
def test_saved_work_in_new_ancestry_survives_ordinary_and_merge_commits(
    repo: FakeRepo, slot: FakeWorktree, merge: bool,
) -> None:
    prepared = head(slot)
    slot.write_file("unfinished", "work")
    saved = slot.record("unfinished\n\nTask-Loop-Wip: attempt", paths="all")
    assert isinstance(saved, Recorded)
    slot.write_file("ordinary", "result")
    ordinary = slot.record("ordinary step", paths="all")
    assert isinstance(ordinary, Recorded)
    if merge:
        person = repo.worktree(repo.path)
        person.write_file("main-change", "main")
        target = person.record("main result", paths="all")
        assert isinstance(target, Recorded)
        assert isinstance(slot.start_merge(str(target.sha)), MergeStarted)
        slot.finish_merge("ordinary merge")
    tip = head(slot)
    assert not is_saved(repo, tip)
    assert saved_since(repo, prepared, tip)
    assert not saved_since(repo, str(saved.sha), tip)


@pytest.fixture
def log(registered: sqlite3.Connection) -> HoldStore:
    registered.execute("UPDATE attempt SET label='auto'")
    log = HoldStore(lambda: registered)
    log.insert(HoldInsert("attempt", "attempt", "stuck:expired_admitted", 101.0))
    return log


def conflict(repo: FakeRepo, slot: FakeWorktree) -> tuple[Source, str, str]:
    person = repo.worktree(repo.path)
    base = head(person)
    person.checkout_new("task/tl-1", "main")
    person.write_file("README", "the task's change\n")
    x = person.record("task work", paths="all")
    assert isinstance(x, Recorded)
    person.checkout("main")
    person.write_file("README", "main's change\n")
    o = person.record("other task", paths="all")
    assert isinstance(o, Recorded)
    slot.checkout(str(x.sha))
    started = slot.start_merge(str(o.sha))
    assert isinstance(started, MergeStarted) and slot.unmerged() == ("README",)
    return Source("tl-1", "attempt", "s1", base, (str(x.sha), str(o.sha))), str(x.sha), str(o.sha)


def head(slot: FakeWorktree) -> str:
    found = next(each.head for each in slot.repo.worktrees() if each.path == slot.path)
    assert found is not None
    return str(found)


def test_unresolved_working_files_and_both_sides_survive_preservation(
    repo: FakeRepo, slot: FakeWorktree, log: HoldStore,
) -> None:
    source, x, o = conflict(repo, slot)
    markers = slot.read_file("README")
    assert markers is not None and "the task's change" in markers and "main's change" in markers
    with pytest.raises(UnmergedPaths):
        slot.capture()  # the pinned shelf deliberately refuses an unresolved index
    assert save(repo, slot, source, x, 123, log) is None
    (saved,) = log.saved("attempt")
    tree = repo.tree(saved.sha)
    assert tree is not None and tree.read("README") == markers.encode()
    assert is_saved(repo, saved.sha) and {x, o} <= {str(each.sha) for each in repo.history([saved.sha])}
    assert saved.source_head == x and head(slot) == x and slot.merging()
    assert slot.read_file("README") == markers
    assert dict(repo.branches("task/"))["task/tl-1"] == saved.sha
    refused = park(slot, source.base)
    assert isinstance(refused, Refused) and refused.reason is SaveReason.MERGE_PENDING
    assert slot.merging() and slot.read_file("README") == markers
    # Preservation records before the owning release is allowed to abort the merge.
    slot.abort_merge()
    assert park(slot, source.base) == source.base
    assert tree.read("README") == markers.encode()


def test_a_finished_detached_merge_is_retained_in_preservation_ancestry(
    repo: FakeRepo, slot: FakeWorktree, log: HoldStore,
) -> None:
    source, x, o = conflict(repo, slot)
    slot.write_file("README", "main's change\nthe task's change\n")
    slot.stage(["README"])
    merged = str(slot.finish_merge("resolve both changes"))
    assert dict(repo.branches("task/"))["task/tl-1"] == x
    assert save(repo, slot, source, merged, 123, log) is None
    (saved,) = log.saved("attempt")
    assert {x, o, merged} <= {str(each.sha) for each in repo.history([saved.sha])}
    assert saved.source_head == merged and head(slot) == merged
    tree = repo.tree(saved.sha)
    assert tree is not None and tree.read("README") == b"main's change\nthe task's change\n"
    assert is_saved(repo, saved.sha)


def test_a_deleted_conflicting_file_is_saved_with_both_original_versions_in_history(
    repo: FakeRepo, slot: FakeWorktree, log: HoldStore,
) -> None:
    source, x, o = conflict(repo, slot)
    slot.remove_file("README")
    assert slot.unmerged() == ("README",)
    assert save(repo, slot, source, x, 123, log) is None
    (saved,) = log.saved("attempt")
    tree, ours, theirs = repo.tree(saved.sha), repo.tree(x), repo.tree(o)
    assert tree is not None and "README" not in tree.files
    assert ours is not None and ours.read("README") == b"the task's change\n"
    assert theirs is not None and theirs.read("README") == b"main's change\n"
    assert slot.merging() and slot.read_file("README") is None


def test_a_capture_failure_preserves_work_for_a_later_save(
    repo: FakeRepo, slot: FakeWorktree, log: HoldStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, x, _ = conflict(repo, slot)
    markers = slot.read_file("README")
    capture = slot.capture

    def unavailable() -> None:
        raise GitUnavailable("index cannot be captured")

    monkeypatch.setattr(slot, "capture", unavailable)
    with pytest.raises(GitUnavailable):
        save(repo, slot, source, x, 123, log)
    assert slot.merging() and slot.read_file("README") == markers
    assert log.saved("attempt") == () and dict(repo.branches("task/"))["task/tl-1"] == x
    monkeypatch.setattr(slot, "capture", capture)
    assert save(repo, slot, source, x, 124, log) is None
    assert len(log.saved("attempt")) == 1 and slot.merging()


def test_a_save_resumes_after_its_ref_write_without_a_duplicate_commit(
    repo: FakeRepo, slot: FakeWorktree, log: HoldStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, x, _ = conflict(repo, slot)
    add = log.add

    def interrupt(*_args: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(log, "add", interrupt)
    with pytest.raises(KeyboardInterrupt):
        save(repo, slot, source, x, 123, log)
    first = dict(repo.branches("task/"))["task/tl-1"]
    assert slot.merging() and log.saved("attempt") == ()
    monkeypatch.setattr(log, "add", add)
    assert save(repo, slot, source, x, 124, log) is None
    assert dict(repo.branches("task/"))["task/tl-1"] == first
    assert [each.sha for each in log.saved("attempt")] == [first]
    assert save(repo, slot, source, x, 125, log) is None and len(log.saved("attempt")) == 1


@pytest.mark.parametrize("missing", [True, False], ids=["missing_inputs", "changed_start"])
def test_an_unaccounted_merge_remains_untouched_and_unsaved(
    repo: FakeRepo, slot: FakeWorktree, log: HoldStore, missing: bool,
) -> None:
    source, x, o = conflict(repo, slot)
    source = replace(source, merge=None if missing else (o, x))
    before = slot.read_file("README")
    found = save(repo, slot, source, x, 123, log)
    assert found is not None and found.reason is (SaveReason.MERGE_INPUTS if missing else SaveReason.MERGE_CHANGED)
    assert found.detail and slot.unmerged() == ("README",) and slot.merging()
    assert slot.read_file("README") == before and log.saved("attempt") == ()
    assert dict(repo.branches("task/"))["task/tl-1"] == x
