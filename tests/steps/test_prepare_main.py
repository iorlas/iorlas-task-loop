"""Slot eligibility depends on the selected task history or origin main, independently of merging them."""

import sqlite3
from pathlib import Path

import pytest
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain import CommandResult, GitUnavailable, Recorded
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from merge_bench import MergeRepo
from round_bench import Factory, Tracker, scripts, task
from test_input_context import GLOSSARY
from test_prepare import BRANCH, admitted, head, leave, pushed, slots

from taskloop.admit import AdmitRefused, AdmitUnavailable
from taskloop.merge.store import MergeStore
from taskloop.prepare import Branch, branch_refusal


@pytest.fixture
def remote() -> FakeRemote:
    found = FakeRemote("https://example.invalid/repo.git")
    found.advance("main", {"README": "old main\n", ".task-loop.json": "{}"})
    return found


@pytest.fixture
def repo(tmp_path: Path, remote: FakeRemote) -> FakeRepo:
    return MergeRepo.clone(remote, tmp_path / "main")


@pytest.mark.parametrize("refs", ["local", "remote", "both"])
def test_new_main_slot_can_continue_the_published_task_tip(
    repo: FakeRepo, remote: FakeRemote, slot: FakeWorktree, tmp_path: Path, refs: str,
) -> None:
    tip = leave(repo, tmp_path, BRANCH, extra=True) if refs == "local" else pushed(repo, tmp_path)
    if refs == "both":
        leave(repo, tmp_path, BRANCH, start=tip)
    target = remote.advance("main", {"other": "landed task\n"})
    assert repo.fetch().ok
    slot.park(target)
    found = branch_refusal(repo, "tl-1", (target,))
    assert isinstance(found, Branch) and found.start == tip and found.passing == (target,)
    assert head(repo, slot.path) == target and slot.branch() is None  # admission writes no Git


def test_selected_local_tip_allows_a_task_only_base_despite_a_stale_remote_tip(
    repo: FakeRepo, remote: FakeRemote, tmp_path: Path,
) -> None:
    old = pushed(repo, tmp_path)
    tip = leave(repo, tmp_path, BRANCH, start=old, extra=True)
    main = remote.advance("main", {"other": "new main\n"})
    assert repo.fetch().ok
    invalid = leave(repo, tmp_path, "other", extra=True)
    found = branch_refusal(repo, "tl-1", (invalid, tip, main))
    assert isinstance(found, Branch) and found.passing == (tip, main) and found.start == tip
    assert branch_refusal(repo, "tl-1", (invalid,)) == "branch_diverged"


def test_origin_main_commits_are_not_foreign_unpublished_work_when_local_main_lags(
    repo: FakeRepo, remote: FakeRemote, tmp_path: Path,
) -> None:
    main = remote.advance("main", {"other": "new main\n"})
    assert repo.fetch().ok
    tip = leave(repo, tmp_path, BRANCH, start=main, extra=True)
    found = branch_refusal(repo, "tl-1", (main,))
    assert isinstance(found, Branch) and found.start == tip


def test_missing_origin_knowledge_is_target_unless_selected_start_proves_the_base(
    repo: FakeRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tip = leave(repo, tmp_path, BRANCH)
    invalid = leave(repo, tmp_path, "other", extra=True)
    refs = repo.refs
    monkeypatch.setattr(repo, "refs", lambda names: tuple(entry for entry in refs(names)
                                                         if entry.name != "refs/remotes/origin/main"))
    assert isinstance(branch_refusal(repo, "tl-1", (tip,)), Branch)
    assert branch_refusal(repo, "tl-1", (invalid,)) == "target"


def test_unreadable_origin_ancestry_is_not_divergence(
    repo: FakeRepo, remote: FakeRemote, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    leave(repo, tmp_path, BRANCH)
    target = remote.advance("main", {"other": "landed\n"})
    assert repo.fetch().ok
    ancestor = repo.is_ancestor

    def read(a: str, b: str) -> bool:
        if b == target:
            raise GitUnavailable("cannot read origin main")
        return ancestor(a, b)

    monkeypatch.setattr(repo, "is_ancestor", read)
    with pytest.raises(GitUnavailable, match="cannot read origin main"):
        branch_refusal(repo, "tl-1", (target,))


@pytest.mark.parametrize("source", ["new", "without_local_main", "local", "remote"])
def test_admission_refreshes_origin_preserves_checkout_merges_retained_work_and_parks_at_recorded_tip(
    factory: sqlite3.Connection, repo: FakeRepo, remote: FakeRemote, slot: FakeWorktree,
    checkouts: PinnedViews, slot_files: FakeSlotFiles, tmp_path: Path, source: str,
) -> None:
    original = head(repo, repo.path)
    retained = None
    if source in ("local", "remote"):
        author = repo.add_worktree(tmp_path / "author", "HEAD")
        author.checkout_new(BRANCH)
        author.write_file("retained.txt", "Earlier task work\n")
        made = author.record("Plan\n\nTask-Loop-Attempt: earlier", paths="all")
        assert isinstance(made, Recorded)
        retained = made.sha
        if source == "remote":
            author.push(BRANCH)
        author.park(retained)
        repo.drop_worktree(author.path)
        if source == "remote":
            repo.delete_branch(BRANCH, expected=retained)
    if source == "without_local_main":
        repo.rename_branch("main", "trunk")
    person = repo.worktree(repo.path)
    person.write_file("owner.txt", "Keep this staged file\n")
    person.stage(["owner.txt"])
    person.write_file("README", "Keep this unstaged change\n")
    before = person.dirty()
    target = remote.advance("main", {"other": "Current origin\n", "docs/glossary.md": GLOSSARY.decode()})
    assert next(ref.sha for ref in repo.refs(["refs/remotes/origin/main"])) == original
    run = Factory(factory, tmp_path, slot, checkouts, slot_files, Tracker(task("tl-1")))
    run.merge_before_dispatch = True
    scripts(run, slot, "tl-1", "tl-2")
    assert run.round() == [("tl-1", "plan", "start", "started")]
    key = run.store.attempt_of("tasks", "tl-1")
    assert key is not None
    work = MergeStore(lambda: factory).get(key[0].attempt_id)
    assert work is not None and work.source == (retained or target)
    if retained is None:
        ref = run.store.input_ref(key[0])
        assert f"Source commit: {target}" in (tmp_path / ref.path).read_text()
    assert run.store.slot_base(key[0]) == target
    assert repo.is_ancestor(target, head(repo, slot.path) or "")
    if retained is not None:
        assert repo.is_ancestor(retained, head(repo, slot.path) or "") and slot.read_file("retained.txt")
    later = remote.advance("main", {"later": "Next landing\n"})
    assert run.round() == [("tl-1", "plan", "verify", "verified release=released branch=published")]
    assert head(repo, slot.path) == target and slot.branch() is None
    assert person.dirty() == before and head(repo, repo.path) == original
    assert person.read_file("owner.txt") == "Keep this staged file\n" and person.read_file("README") == "Keep this unstaged change\n"
    assert dict(repo.branches()).get("main") == (None if source == "without_local_main" else original)
    run.tracker.beads.pop("tl-1")
    run.tracker.beads["tl-2"] = task("tl-2")
    assert ("tl-2", "plan", "start", "started") in run.round()
    second = run.store.attempt_of("tasks", "tl-2")
    assert second is not None and run.store.slot_base(second[0]) == later


@pytest.mark.parametrize("failure", ["raised", "result", "missing"])
def test_refresh_failure_has_no_input_claim_or_reservation(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    slots(factory, repo, root, 1)
    refs = repo.refs

    def unavailable(*args: object, **kwargs: object) -> object:
        assert not factory.in_transaction
        assert args == ("origin",) and kwargs == {
            "refspecs": ["+refs/heads/main:refs/remotes/origin/main"], "timeout": 120,
        }
        if failure == "raised":
            raise GitUnavailable("offline")
        return CommandResult(ok=False, output="offline")

    if failure == "missing":
        monkeypatch.setattr(repo, "refs", lambda names: tuple(ref for ref in refs(names) if ref.name != "refs/remotes/origin/main"))
    else:
        monkeypatch.setattr(repo, "fetch", unavailable)
    result, claims = admitted(factory, repo, root, tmp_path)
    if failure == "missing":
        assert isinstance(result, AdmitRefused) and result.reason == "target" and result.detail
    else:
        assert isinstance(result, AdmitUnavailable) and result.what == "git" and result.detail
    assert not claims.calls
    assert factory.execute("SELECT count(*) FROM attempt").fetchone() == (0,)
    assert factory.execute("SELECT count(*) FROM reservation").fetchone() == (0,)
