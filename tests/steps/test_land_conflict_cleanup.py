"""Interrupted saved-work cleanup retains bytes and exact reservation custody."""

from collections.abc import Generator, Sequence
from pathlib import Path

import land_conflict_bench
import pytest
from git_porcelain import GitUnavailable, Sha
from git_porcelain.testing import FakeRepo, FakeWorktree
from land_conflict_bench import ExecutionCase
from merge_bench import head

from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_types import AttemptKey
from taskloop.land_conflict.cleanup_models import CleanupPhase
from taskloop.land_conflict.models import Save
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Completed, Disposition, InProgress, Terminal, Unavailable


@pytest.fixture
def repo(tmp_path: Path) -> FakeRepo:
    return land_conflict_bench.execution_repo(tmp_path)


@pytest.fixture
def execution_case(on_slot: Path, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path) -> Generator[ExecutionCase]:
    yield from land_conflict_bench.execution_case(on_slot, repo, slot, tmp_path)


def edit(slot: FakeWorktree) -> None:
    slot.write_file("README", "working tracked bytes\n")
    slot.stage(("README",))
    slot.write_file("README", "latest tracked bytes\n")
    slot.write_file("addition", "staged bytes\n")
    slot.stage(("addition",))
    slot.write_file("notes/local", "untracked bytes\n")
    slot.write_file("notes/other", "other untracked bytes\n")
    slot.write_file(".gitignore", "ignored\ncache*/\n")
    slot.write_file("ignored", "ignored bytes\n")
    slot.write_file("cache [one]/data", "ignored nested bytes\n")


def retained(c: ExecutionCase) -> Save:
    saved = c.ports.store.saved(c.record.key)
    assert saved is not None
    assert c.con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (
        c.record.key.attempt_id, c.record.key.reservation_generation)
    assert dict(c.ports.repo.branches("task/")) == {"task/tl-1": c.record.request.checked}
    tree = c.ports.repo.tree(saved.commit or "")
    assert tree is not None
    assert tree.read("README") == b"latest tracked bytes\n"
    assert tree.read("addition") == b"staged bytes\n"
    assert tree.read("notes/local") == b"untracked bytes\n"
    assert tree.read("notes/other") == b"other untracked bytes\n"
    assert "ignored" not in tree.files and "cache [one]/data" not in tree.files
    assert c.slot.read_file("ignored") == "ignored bytes\n"
    assert c.slot.read_file("cache [one]/data") == "ignored nested bytes\n"
    assert dict(c.ports.repo.branches("task-loop/conflicts/")) == {saved.ref.removeprefix("refs/heads/"): saved.commit}
    return saved


def interrupt(c: ExecutionCase, patch: pytest.MonkeyPatch, boundary: str, after: bool) -> None:
    exclude, park = FakeWorktree.exclude, FakeWorktree.park

    def stop(when: bool) -> None:
        assert not c.con.in_transaction
        if when == after:
            raise KeyboardInterrupt

    def excluding(self: FakeWorktree, patterns: Sequence[str]) -> None:
        if boundary == "exclude" and c.calls:
            stop(False)
        exclude(self, patterns)
        if boundary == "exclude" and c.calls:
            stop(True)

    def parking(self: FakeWorktree, base: str, *, clean_keep: Sequence[str] | None = None, keep_ignored: bool = False) -> Sha:
        if not c.calls:
            return park(self, base, clean_keep=clean_keep, keep_ignored=keep_ignored)
        assert clean_keep == () and keep_ignored
        if boundary == "park":
            stop(False)
        if boundary == "partial":
            park(self, base, keep_ignored=keep_ignored)
            self.remove_file("notes/local")
            raise KeyboardInterrupt
        value = park(self, base, clean_keep=clean_keep, keep_ignored=keep_ignored)
        if boundary == "park":
            stop(True)
        return value

    patch.setattr(FakeWorktree, "exclude", excluding)
    patch.setattr(FakeWorktree, "park", parking)
    interrupt_reset(c, patch, boundary, after)
    interrupt_store(c, patch, boundary, after)


def interrupt_reset(c: ExecutionCase, patch: pytest.MonkeyPatch, boundary: str, after: bool) -> None:
    reset = FakeWorktree.reset

    def resetting(self: FakeWorktree, rev: str, *, mode: str = "mixed") -> None:
        assert not c.con.in_transaction and mode == "hard"
        if boundary == "reset" and c.calls and not after:
            raise KeyboardInterrupt
        reset(self, rev, mode="hard")
        if boundary == "reset" and c.calls and after:
            raise KeyboardInterrupt

    patch.setattr(FakeWorktree, "reset", resetting)


def interrupt_store(c: ExecutionCase, patch: pytest.MonkeyPatch, boundary: str, after: bool) -> None:
    save = ConflictStore.save

    def put(self: ConflictStore, key: AttemptKey, previous: Save | None, updated: Save) -> Save:
        assert not c.con.in_transaction
        cleanup = updated.cleanup
        phases = {"intent": CleanupPhase.EXCLUDE, "ready": CleanupPhase.PARK, "complete": CleanupPhase.COMPLETE}
        selected = cleanup is not None and cleanup.phase is phases.get(boundary) and (
            previous is None or previous.cleanup != cleanup)
        if selected and not after:
            raise KeyboardInterrupt
        value = save(self, key, previous, updated)
        if selected and after:
            raise KeyboardInterrupt
        return value

    patch.setattr(ConflictStore, "save", put)


@pytest.mark.parametrize("merging", [False, True])
@pytest.mark.parametrize("boundary", ["intent", "exclude", "ready", "park", "complete", "partial"])
@pytest.mark.parametrize("after", [False, True])
def test_cleanup_restart_preserves_saved_and_ignored_bytes(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, merging: bool, boundary: str, after: bool,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER

    def edits(slot: FakeWorktree) -> None:
        if not merging:
            slot.abort_merge()
        edit(slot)

    c.edit = edits
    with monkeypatch.context() as patch:
        interrupt(c, patch, boundary, after)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    before = retained(c)
    c.restart()
    result = c.resume()
    assert isinstance(result, Terminal) and result.explanation == "Retain both sides."
    complete = retained(c)
    assert complete.cleanup is not None and complete.cleanup.phase is CleanupPhase.COMPLETE
    assert complete.model_dump(exclude={"abort", "cleanup"}) == before.model_dump(exclude={"abort", "cleanup"})
    assert head(c.slot) == c.record.request.checked and c.slot.branch() is None and not c.slot.merging()
    assert not c.slot.dirty().raw and not c.slot.unmerged()
    assert c.slot.read_file("notes/local") is None and c.slot.read_file("notes/other") is None
    assert c.slot.read_file("addition") is None and c.slot.read_file(".gitignore") is None
    c.restart()
    assert c.resume() == result and retained(c) == complete and c.calls == 1


@pytest.mark.parametrize("after", [False, True])
def test_dirty_tracked_cleanup_resumes_reset(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, after: bool) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER

    def edits(slot: FakeWorktree) -> None:
        slot.abort_merge()
        edit(slot)

    c.edit = edits
    with monkeypatch.context() as patch:
        interrupt(c, patch, "reset", after)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    retained(c)
    c.restart()
    assert isinstance(c.resume(), Terminal) and not c.slot.dirty().raw and c.calls == 1
    retained(c)


@pytest.mark.parametrize("changed", ["tracked", "untracked", "ignored", "new", "head", "branch", "ref", "live", "generation"])
@pytest.mark.parametrize("after", [False, True])
def test_foreign_changes_keep_cleanup_and_custody_pending(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, changed: str, after: bool,
) -> None:
    c = execution_case
    c.disposition, c.edit = Disposition.OWNER, edit
    with monkeypatch.context() as patch:
        interrupt(c, patch, "park", after)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    saved = retained(c)
    if changed in ("tracked", "untracked", "ignored", "new"):
        path = {"tracked": "README", "untracked": "notes/other", "ignored": "ignored", "new": "foreign"}[changed]
        c.slot.write_file(path, "foreign bytes\n")
    elif changed == "head":
        c.slot.park(c.record.request.target)
    elif changed == "branch":
        c.slot.checkout_new("foreign", head(c.slot))
    elif changed == "ref":
        c.ports.repo.update_ref(saved.ref, saved.source, expected=saved.commit)
    elif changed == "live":
        c.gone = False
    else:
        c.con.execute("UPDATE reservation SET generation=generation+1")
    before = c.con.execute("SELECT save_data FROM land_conflict").fetchone()
    reservation = c.con.execute("SELECT * FROM reservation").fetchall()
    c.restart()
    monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_kwargs: pytest.fail("foreign cleanup"))
    monkeypatch.setattr(FakeWorktree, "reset", lambda *_args, **_kwargs: pytest.fail("foreign reset"))
    result = c.resume()
    assert isinstance(result, (Unavailable, InProgress)) and result.explanation and c.calls == 1
    assert c.con.execute("SELECT save_data FROM land_conflict").fetchone() == before
    assert c.con.execute("SELECT * FROM reservation").fetchall() == reservation


def test_cleanup_failure_keeps_intent(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    c = execution_case
    c.disposition, c.edit = Disposition.OWNER, edit

    park = FakeWorktree.park

    def fail(self: FakeWorktree, base: str, *, clean_keep: Sequence[str] | None = None, keep_ignored: bool = False) -> Sha:
        if c.calls:
            raise GitUnavailable("cleanup failed")
        return park(self, base, clean_keep=clean_keep, keep_ignored=keep_ignored)

    with monkeypatch.context() as patch:
        patch.setattr(FakeWorktree, "park", fail)
        result = c.resume()
    assert isinstance(result, Unavailable) and "cleanup failed" in result.explanation
    assert retained(c).cleanup is not None
    c.restart()
    assert isinstance(c.resume(), Terminal) and c.calls == 1
    retained(c)


def test_accepted_result_bypasses_cleanup(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    c = execution_case
    exclude = FakeWorktree.exclude
    reset = FakeWorktree.reset

    def excluding(self: FakeWorktree, patterns: Sequence[str]) -> None:
        assert not c.calls
        exclude(self, patterns)

    def resetting(self: FakeWorktree, rev: str, *, mode: str = "mixed") -> None:
        assert not c.calls and mode == "hard"
        reset(self, rev, mode="hard")

    monkeypatch.setattr(FakeWorktree, "exclude", excluding)
    monkeypatch.setattr(FakeWorktree, "reset", resetting)
    assert isinstance(c.resume(), Completed)
    saved = c.ports.store.saved(c.record.key)
    assert saved is not None and saved.cleanup is None


def test_cleanup_transitions_freeze_expectations(execution_case: ExecutionCase) -> None:
    c = execution_case
    c.disposition, c.edit = Disposition.OWNER, edit
    assert isinstance(c.resume(), Terminal)
    saved = retained(c)
    assert saved.cleanup is not None
    for cleanup in (None, saved.cleanup.model_copy(update={"phase": CleanupPhase.PARK}),
                    saved.cleanup.model_copy(update={"ignored": {}})):
        with pytest.raises(StoreRefused):
            c.ports.store.save(c.record.key, saved, saved.model_copy(update={"cleanup": cleanup}))


def test_ignored_collision_prevents_destructive_cleanup(execution_case: ExecutionCase) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER

    def edits(slot: FakeWorktree) -> None:
        slot.abort_merge()
        slot.remove_file("README")
        slot.stage(("README",))
        slot.write_file(".gitignore", "README\n")
        slot.write_file("README", "ignored bytes at tracked path\n")

    c.edit = edits
    result = c.resume()
    assert isinstance(result, Unavailable) and "ignored path overlaps" in result.explanation
    assert c.slot.read_file("README") == "ignored bytes at tracked path\n"
    saved = c.ports.store.saved(c.record.key)
    assert saved is not None and saved.cleanup is None
    assert c.con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (
        c.record.key.attempt_id, c.record.key.reservation_generation)
    c.restart()
    assert isinstance(c.resume(), Unavailable) and c.calls == 1
    assert c.slot.read_file("README") == "ignored bytes at tracked path\n"
