"""Retained task history, immutable targets, conflict resolution and action reconciliation."""

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain import GitUnavailable, Pushed, Recorded
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from merge_bench import Bench, MergeRepo, bench, head

from taskloop import wip
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AnswerState, AttemptKey
from taskloop.factory_commit import Committed, settle
from taskloop.merge.models import Completed, Phase, Reason, Terminal, Work
from taskloop.prepare import Branch, branch_refusal


@pytest.fixture
def remote() -> FakeRemote:
    found = FakeRemote("https://example.invalid/repo.git")
    found.advance("main", {"README": "old main\n"})
    return found


@pytest.fixture
def repo(tmp_path: Path, remote: FakeRemote) -> FakeRepo:
    return MergeRepo.clone(remote, tmp_path / "main")


@pytest.fixture
def clean(factory: sqlite3.Connection, repo: FakeRepo, remote: FakeRemote, slot: FakeWorktree,
          slot_files: FakeSlotFiles, checkouts: PinnedViews) -> Bench:
    return bench(factory, repo, remote, slot, slot_files, checkouts)


def test_clean_merge_retains_plan_and_main_without_resolution_or_local_main_movement(clean: Bench) -> None:
    local_main = dict(clean.repo.branches())["main"]
    found = clean.operation().resume(clean.work)
    assert isinstance(found, Completed) and found.source == clean.work.source
    assert clean.repo.is_ancestor(found.source, found.commit) and clean.repo.is_ancestor(found.target, found.commit)
    assert clean.slot.read_file("docs/design/tl-1/plan.md") == "Retain the plan.\n"
    assert clean.slot.read_file("other") == "another landed task\n" and clean.slot.read_file("README") == "current main\n"
    assert clean.calls == ["setup"] and clean.slot.branch() == "task/tl-1"
    assert dict(clean.repo.branches())["main"] == local_main
    clean.slot.park(clean.work.base)
    assert isinstance(branch_refusal(clean.repo, "tl-1", (found.target,)), Branch)
    stored = clean.store.get("attempt")
    assert stored is not None and stored.phase is Phase.COMPLETE and stored.target == found.target


def test_textual_conflict_resolves_without_replanning(factory: sqlite3.Connection, repo: FakeRepo, remote: FakeRemote,
              slot: FakeWorktree, slot_files: FakeSlotFiles, checkouts: PinnedViews) -> None:
    case = bench(factory, repo, remote, slot, slot_files, checkouts, conflict=True)
    found = case.operation().resume(case.work)
    assert isinstance(found, Completed) and case.calls == ["setup", "resolve"]
    assert slot.read_file("README") == "the task\ncurrent main\n" and not slot.merging()
    assert repo.is_ancestor(case.work.source, found.commit) and repo.is_ancestor(found.target, found.commit)


@pytest.mark.parametrize("action", ["start_merge", "finish_merge", "take_branch", "park"])
def test_crash_after_an_action_adopts_it_without_duplicate_merge(clean: Bench, monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    operation = clean.operation()
    original: Callable[..., object] = getattr(FakeWorktree, action)
    calls = 0

    def crash(self: FakeWorktree, *args: object, **kwargs: object) -> object:
        nonlocal calls
        result = original(self, *args, **kwargs)
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(FakeWorktree, action, crash)
    with pytest.raises(KeyboardInterrupt):
        operation.resume(clean.work)
    stored = clean.store.get("attempt")
    assert stored is not None
    first_head = head(clean.slot)
    monkeypatch.setattr(FakeWorktree, action, original)
    found = clean.operation().resume(stored)
    assert isinstance(found, Completed)
    if action in ("finish_merge", "take_branch"):
        assert found.commit == first_head
    merges = [entry for entry in clean.repo.history([found.commit]) if "Task-Loop-Merge-Target:" in entry.body]
    assert len(merges) == 1


def test_fetch_failure_keeps_a_resumable_intent(clean: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    fetch = clean.repo.fetch

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise GitUnavailable("offline")

    monkeypatch.setattr(clean.repo, "fetch", unavailable)
    result = clean.operation().resume(clean.work)
    assert not isinstance(result, (Completed, Terminal)) and result.explanation
    assert clean.store.get("attempt") == clean.work
    monkeypatch.setattr(clean.repo, "fetch", fetch)
    assert isinstance(clean.operation().resume(clean.work), Completed)


def test_target_moves_after_recording_do_not_restart_or_replace_the_recorded_target(clean: Bench) -> None:
    operation = clean.operation()

    def moved(work: Work) -> None:
        clean.setup(work)
        clean.remote.advance("main", {"later": "next landing\n"})

    operation.setup = moved
    found = operation.resume(clean.work)
    assert isinstance(found, Completed) and clean.slot.read_file("later") is None
    assert clean.slot.read_file("docs/design/tl-1/plan.md") is not None


def test_source_already_containing_main_needs_no_additional_merge(clean: Bench) -> None:
    first = clean.operation().resume(clean.work)
    assert isinstance(first, Completed)
    work = clean.store.start(clean.work.model_copy(update={"attempt_id": "second", "source": first.commit}))
    second = clean.operation().resume(work)
    assert isinstance(second, Completed) and second.commit == first.commit and clean.calls == ["setup"]


def test_source_behind_main_uses_the_descendant_main_commit(clean: Bench) -> None:
    person = clean.repo.worktree(clean.repo.path)
    person.merge_ff("refs/remotes/origin/main")
    person.start_merge(clean.work.source)
    made = person.finish_merge("Main already contains this plan")
    assert isinstance(person.push("main"), Pushed)
    found = clean.operation().resume(clean.work)
    assert isinstance(found, Completed) and found.commit == made and clean.calls == []
    assert clean.slot.read_file("docs/design/tl-1/plan.md") == "Retain the plan.\n"


def test_detached_continuation_retains_the_original_task_ref(clean: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    target = {entry.name: entry.sha for entry in clean.repo.refs(["refs/remotes/origin/main"])}["refs/remotes/origin/main"]
    clean.slot.park(clean.work.source)
    work = clean.store.put(clean.work, clean.work.model_copy(update={"branch": None, "target": target}))
    monkeypatch.setattr(clean.repo, "fetch", lambda *_args, **_kw: pytest.fail("the owner already supplied an immutable target"))
    found = clean.operation().resume(work)
    assert isinstance(found, Completed) and clean.slot.branch() is None
    assert dict(clean.repo.branches())["task/tl-1"] == clean.work.source


def test_merging_saved_work_keeps_its_ordinary_review_requirement(clean: Bench, registered: sqlite3.Connection) -> None:
    saved = clean.slot.record("Save work\n\nTask-Loop-Attempt: prior\nTask-Loop-Wip: prior", paths="all", allow_empty=True)
    assert isinstance(saved, Recorded)
    work = clean.store.put(clean.work, clean.work.model_copy(update={"source": saved.sha}))
    found = clean.operation().resume(work)
    assert isinstance(found, Completed) and wip.needs_review(clean.repo, found.commit)
    record = AttemptStore(lambda: registered).load(AttemptKey("attempt", "dispatch", 1))
    assert record is not None
    reviewed = settle(clean.views, clean.files, record.admission, found.commit,
                      AnswerState("valid", "unchanged", "keep"), lambda: None)
    assert isinstance(reviewed, Committed) and reviewed.sha != found.commit
    before, after = clean.repo.tree(found.commit), clean.repo.tree(reviewed.sha)
    assert before is not None and after is not None and before.files == after.files
    assert not wip.needs_review(clean.repo, reviewed.sha)


def test_nontextual_conflicts_hold_without_a_resolution_execution(clean: Bench) -> None:
    clean.slot.write_file("README", "the task\0binary\n")
    source = clean.slot.record("Task binary work\n\nTask-Loop-Attempt: prior", paths="all")
    assert isinstance(source, Recorded)
    work = clean.store.put(clean.work, clean.work.model_copy(update={"source": source.sha}))
    found = clean.operation().resume(work)
    assert isinstance(found, Terminal) and found.reason is Reason.UNSUPPORTED
    assert clean.calls == ["setup"] and clean.slot.merging()


def test_crash_after_ref_attachment_adopts_the_attached_result(clean: Bench, monkeypatch: pytest.MonkeyPatch) -> None:
    update = clean.repo.update_ref
    calls = 0

    def interrupted(ref: str, new: str, *, expected: str | None) -> None:
        nonlocal calls
        update(ref, new, expected=expected)
        calls += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(clean.repo, "update_ref", interrupted)
    with pytest.raises(KeyboardInterrupt):
        clean.operation().resume(clean.work)
    work = clean.store.get("attempt")
    assert work is not None and work.phase is Phase.ATTACH and work.result == head(clean.slot)
    assert dict(clean.repo.branches())["task/tl-1"] == work.result
    monkeypatch.setattr(clean.repo, "update_ref", lambda *_a, **_kw: pytest.fail("the attached ref must be adopted"))
    found = clean.operation().resume(work)
    assert isinstance(found, Completed) and found.commit == work.result and calls == 1
