"""Owning release preserves merge files and both inputs before abort; terminal holds stay held."""

import sqlite3
from contextlib import nullcontext
from pathlib import Path

import pytest
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain import GitUnavailable
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from merge_bench import Bench, MergeRepo, bench, head

from taskloop.attempt_status import StatusPorts, current_view
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.hold_status import cause, reingests
from taskloop.hold_store import HoldInsert, HoldStore
from taskloop.merge.models import Phase, Reason, Terminal, Work
from taskloop.slot_release import NotReleased, Released, SlotRelease
from taskloop.wip import is_saved


@pytest.fixture
def remote() -> FakeRemote:
    found = FakeRemote("https://example.invalid/repo.git")
    found.advance("main", {"README": "old main\n"})
    return found


@pytest.fixture
def repo(tmp_path: Path, remote: FakeRemote) -> FakeRepo:
    return MergeRepo.clone(remote, tmp_path / "main")


@pytest.fixture
def conflict(registered: sqlite3.Connection, repo: FakeRepo, remote: FakeRemote, slot: FakeWorktree,
             slot_files: FakeSlotFiles, checkouts: PinnedViews) -> Bench:
    case = bench(registered, repo, remote, slot, slot_files, checkouts, conflict=True)
    operation = case.operation()

    def owner(_work: Work) -> Terminal:
        return Terminal(reason=Reason.OWNER, explanation="The task's text and main need a semantic decision.")

    operation.resolve = owner
    assert isinstance(operation.resume(case.work), Terminal)
    return case


def releaser(con: sqlite3.Connection, case: Bench) -> SlotRelease:
    return SlotRelease(AttemptStore(lambda: con), case.views, case.files, lambda _entry: "gone", lambda _worker: True,
                       lambda _slot, _attempt: nullcontext(), lambda _root, _task: True, lambda: 20,
                       lambda _process: "gone", lambda _path: True, HoldStore(lambda: con))


def test_unlabelled_terminal_merge_holds_and_preserves_before_abort(conflict: Bench, registered: sqlite3.Connection) -> None:
    store = AttemptStore(lambda: registered)
    view = current_view(StatusPorts(store, lambda _entry: "gone", lambda: 10, lambda _key: None, lambda: "boot"), "tasks", "tl-1")
    assert view is not None and view.next == "hold" and cause(view) == "merge:needs_owner" and view.result.explanation
    log = HoldStore(lambda: registered)
    row = log.insert(HoldInsert("attempt", "attempt", "merge:needs_owner", 10))
    assert row.label is None and not reingests("on_hold", row, "auto")
    markers = conflict.slot.read_file("README")
    result = releaser(registered, conflict).release(AttemptKey("attempt", "dispatch", 1), True)
    assert isinstance(result, Released) and result.claim == "unclaimed"
    assert head(conflict.slot) == conflict.work.base and conflict.slot.branch() is None and not conflict.slot.merging()
    (saved,) = log.saved("attempt")
    assert is_saved(conflict.repo, saved.sha)
    tree = conflict.repo.tree(saved.sha)
    assert tree is not None and markers is not None and tree.read("README") == markers.encode()
    work = conflict.store.get("attempt")
    assert work is not None and work.phase is Phase.TERMINAL
    assert conflict.repo.is_ancestor(work.source, saved.sha) and conflict.repo.is_ancestor(work.target or "", saved.sha)
    assert registered.execute("SELECT count(*) FROM reservation").fetchone() == (0,)


def test_preservation_failure_keeps_the_merge_and_reservation(
    conflict: Bench, registered: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = HoldStore(lambda: registered)
    log.insert(HoldInsert("attempt", "attempt", "merge:needs_owner", 10))

    def unavailable(*_args: object) -> None:
        raise GitUnavailable("capture failed")

    monkeypatch.setattr(FakeWorktree, "capture", unavailable)
    result = releaser(registered, conflict).release(AttemptKey("attempt", "dispatch", 1), True)
    assert isinstance(result, NotReleased) and result.kind == "unavailable"
    assert conflict.slot.merging() and registered.execute("SELECT count(*) FROM reservation").fetchone() == (1,)
    assert log.saved("attempt") == ()


def test_crash_after_abort_adopts_preservation_without_saving_a_reverted_tree(
    conflict: Bench, registered: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = HoldStore(lambda: registered)
    log.insert(HoldInsert("attempt", "attempt", "merge:needs_owner", 10))
    abort = FakeWorktree.abort_merge

    def interrupted(self: FakeWorktree) -> None:
        assert len(log.saved("attempt")) == 1  # durable preservation must precede the abort
        abort(self)
        raise KeyboardInterrupt

    monkeypatch.setattr(FakeWorktree, "abort_merge", interrupted)
    with pytest.raises(KeyboardInterrupt):
        releaser(registered, conflict).release(AttemptKey("attempt", "dispatch", 1), True)
    saved = log.saved("attempt")
    assert len(saved) == 1 and not conflict.slot.merging()
    monkeypatch.setattr(FakeWorktree, "abort_merge", abort)
    found = releaser(registered, conflict).release(AttemptKey("attempt", "dispatch", 1), True)
    assert isinstance(found, Released) and log.saved("attempt") == saved
    assert dict(conflict.repo.branches())["task/tl-1"] == saved[0].sha
