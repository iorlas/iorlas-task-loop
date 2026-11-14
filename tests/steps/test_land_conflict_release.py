"""Release requires independent base evidence, exact atomic custody, and effect-free historical replay."""

from collections.abc import Generator, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Never

import land_conflict_bench
import pytest
from git_porcelain import GitUnavailable, Recorded, Sha
from git_porcelain.testing import FakeRepo, FakeWorktree
from land_conflict_bench import ExecutionCase
from merge_bench import head

from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_types import AttemptKey
from taskloop.land_conflict.abort import AbortMerge
from taskloop.land_conflict.abort_models import Checkout
from taskloop.land_conflict.models import Record, Save
from taskloop.land_conflict.release_models import ReleasePhase
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Disposition, Terminal, Unavailable, Work


@pytest.fixture
def repo(tmp_path: Path) -> FakeRepo:
    return land_conflict_bench.execution_repo(tmp_path)


@pytest.fixture
def execution_case(on_slot: Path, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path) -> Generator[ExecutionCase]:
    author = repo.add_worktree(tmp_path / "base-author", head(slot))
    author.write_file("README", "admitted base\n")
    author.write_file("base-only", "base bytes\n")
    base = author.record("admitted base", paths="all")
    assert isinstance(base, Recorded)
    repo.drop_worktree(author.path)
    slot.park(str(base.sha))
    yield from land_conflict_bench.execution_case(on_slot, repo, slot, tmp_path, lambda wt: wt.remove_file("base-only"))


def edits(slot: FakeWorktree) -> None:
    slot.write_file("README", "saved edits\n")
    slot.write_file("notes", "saved untracked bytes\n")
    slot.write_file(".gitignore", "ignored\n")
    slot.write_file("ignored", "ignored bytes\n")


def pending(c: ExecutionCase, patch: pytest.MonkeyPatch, *, parked: bool = False) -> Save:
    c.disposition, c.edit = Disposition.OWNER, edits
    save = ConflictStore.save

    def put(self: ConflictStore, key: AttemptKey, previous: Save | None, updated: Save) -> Save:
        value = save(self, key, previous, updated)
        if updated.release is not None:
            raise KeyboardInterrupt
        return value

    def release(self: ConflictStore, key: AttemptKey, previous: Save, updated: Save) -> Save:
        raise KeyboardInterrupt

    with patch.context() as context:
        if parked:
            context.setattr(ConflictStore, "release", release)
        else:
            context.setattr(ConflictStore, "save", put)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    saved = c.ports.store.saved(c.record.key)
    assert saved is not None and saved.release is not None and saved.release.phase is ReleasePhase.PENDING
    assert c.ports.store.completed(c.record.key) is None
    return saved


def test_base_is_independent_and_release_keeps_saved_work(execution_case: ExecutionCase) -> None:
    c = execution_case
    assert c.record.base not in (c.record.request.checked, c.record.request.target)
    c.disposition, c.edit = Disposition.OWNER, edits
    result = c.resume()
    assert isinstance(result, Terminal)
    saved = c.ports.store.completed(c.record.key)
    assert saved is not None and saved.release is not None and saved.cleanup is not None
    assert saved.cleanup.after.head == c.record.request.checked and saved.release.after.head == c.record.base
    assert head(c.slot) == c.record.base and c.slot.branch() is None and not c.slot.merging()
    assert not c.slot.dirty().raw and not c.slot.unmerged()
    assert c.slot.read_file("README") == "admitted base\n" and c.slot.read_file("base-only") == "base bytes\n"
    assert c.slot.read_file("ignored") == "ignored bytes\n" and c.slot.read_file("notes") is None
    assert "ignored" in c.slot.dirty(ignored_under=(".",)).ignored
    tree = c.ports.repo.tree(saved.commit or "")
    assert tree is not None and tree.read("README") == b"saved edits\n" and tree.read("notes") == b"saved untracked bytes\n"
    assert dict(c.ports.repo.branches("task-loop/conflicts/")) == {saved.ref.removeprefix("refs/heads/"): saved.commit}
    assert c.con.execute("SELECT count(*) FROM reservation").fetchone() == (0,)
    assert c.con.execute("SELECT generation FROM slot WHERE name=?", (c.record.slot,)).fetchone() == (
        c.record.key.reservation_generation,)
    with pytest.raises(StoreRefused):
        c.ports.store.load(c.record.key)


@pytest.mark.parametrize("after", [False, True])
def test_parking_interruption_is_observed_before_retry(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, after: bool,
) -> None:
    c = execution_case
    pending(c, monkeypatch)
    park = FakeWorktree.park
    calls: list[str] = []

    def parking(self: FakeWorktree, base: str, *, clean_keep: Sequence[str] | None = None, keep_ignored: bool = False) -> Sha:
        assert not c.con.in_transaction and clean_keep == () and keep_ignored
        calls.append(base)
        if after:
            park(self, base, clean_keep=clean_keep, keep_ignored=keep_ignored)
        raise KeyboardInterrupt

    with monkeypatch.context() as context:
        context.setattr(FakeWorktree, "park", parking)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    c.restart()

    def counted(self: FakeWorktree, base: str, *, clean_keep: Sequence[str] | None = None, keep_ignored: bool = False) -> Sha:
        calls.append(base)
        return park(self, base, clean_keep=clean_keep, keep_ignored=keep_ignored)

    monkeypatch.setattr(FakeWorktree, "park", counted)
    assert isinstance(c.resume(), Terminal) and calls == [c.record.base] * (1 if after else 2)
    assert c.ports.store.completed(c.record.key) is not None


@pytest.mark.parametrize("changed", ["false_success", "observation", "ignored", "protection", "index", "branch", "untracked"])
def test_unverified_parking_retains_custody(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, changed: str,
) -> None:
    c = execution_case
    saved = pending(c, monkeypatch)
    park = FakeWorktree.park
    observe = AbortMerge.observe

    def parking(self: FakeWorktree, base: str, *, clean_keep: Sequence[str] | None = None, keep_ignored: bool = False) -> Sha:
        if changed == "false_success":
            return Sha(base)
        value = park(self, base, clean_keep=clean_keep, keep_ignored=keep_ignored)
        if changed == "ignored":
            self.write_file("ignored", "changed bytes")
        elif changed == "protection":
            self.state().exclude.clear()
        elif changed == "index":
            self.write_file("staged", "new index")
            self.stage(("staged",))
        elif changed == "branch":
            self.checkout_force("foreign", base)
        elif changed == "untracked":
            self.write_file("late", "new bytes")
        return value

    def observing(self: AbortMerge, record: Record, work: Work) -> Checkout:
        if changed == "observation" and head(c.slot) == c.record.base:
            raise GitUnavailable("independent evidence unavailable")
        return observe(self, record, work)

    monkeypatch.setattr(FakeWorktree, "park", parking)
    monkeypatch.setattr(AbortMerge, "observe", observing)
    result = c.resume()
    assert isinstance(result, Unavailable) and result.explanation
    assert c.ports.store.saved(c.record.key) == saved and c.ports.store.completed(c.record.key) is None
    assert c.con.execute("SELECT attempt_id FROM reservation").fetchone() == (c.record.key.attempt_id,)
    if changed not in ("false_success", "observation"):
        monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_kwargs: pytest.fail("destructive retry"))
        assert isinstance(c.resume(), Unavailable)


def test_ignored_overlap_with_base_prevents_parking(execution_case: ExecutionCase) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER

    def edit(slot: FakeWorktree) -> None:
        edits(slot)
        slot.write_file(".gitignore", "ignored\nbase-only\n")
        slot.write_file("base-only", "ignored base collision\n")

    c.edit = edit
    result = c.resume()
    assert isinstance(result, Unavailable) and "overlaps the admitted base" in result.explanation
    assert c.slot.read_file("base-only") == "ignored base collision\n" and head(c.slot) == c.record.request.checked
    assert c.ports.store.completed(c.record.key) is None and c.ports.store.saved(c.record.key) is not None


def test_atomic_release_rolls_back_both_writes(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    c = execution_case
    saved = pending(c, monkeypatch, parked=True)
    assert saved.release is not None
    updated = saved.model_copy(update={"release": saved.release.model_copy(update={"phase": ReleasePhase.COMPLETE})})
    c.con.execute("CREATE TEMP TRIGGER refuse_release BEFORE DELETE ON reservation "
                  "BEGIN SELECT RAISE(ABORT,'stop'); END")
    with pytest.raises(StoreUnavailable):
        c.ports.store.release(c.record.key, saved, updated)
    assert c.ports.store.saved(c.record.key) == saved and c.ports.store.completed(c.record.key) is None
    c.con.execute("DROP TRIGGER refuse_release")
    assert c.ports.store.release(c.record.key, saved, updated) == updated
    with pytest.raises(StoreRefused):
        c.ports.store.release(c.record.key, saved, updated)
    assert c.ports.store.completed(c.record.key) == updated


@pytest.mark.parametrize("after", [False, True])
def test_release_completion_interruption_is_restartable(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, after: bool,
) -> None:
    c = execution_case
    saved = pending(c, monkeypatch, parked=True)
    release = ConflictStore.release

    def interrupted(self: ConflictStore, key: AttemptKey, previous: Save, updated: Save) -> Save:
        if after:
            release(self, key, previous, updated)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(ConflictStore, "release", interrupted)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    c.restart()
    monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_kwargs: pytest.fail("already parked"))
    assert saved.release is not None and c.resume() == saved.release.result
    assert c.ports.store.completed(c.record.key) is not None and c.calls == 1


def test_release_preserves_unrelated_reservations(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    c = execution_case
    pending(c, monkeypatch, parked=True)
    c.con.execute("INSERT INTO slot(repo_id,name,path,generation) VALUES (?,'other','/other',7)", (c.record.request.repo_id,))
    c.con.execute("INSERT INTO reservation(repo_id,slot,attempt_id,generation) VALUES (?,'other','other-attempt',7)",
                  (c.record.request.repo_id,))
    assert isinstance(c.resume(), Terminal)
    assert c.con.execute("SELECT slot,attempt_id,generation FROM reservation").fetchall() == [("other", "other-attempt", 7)]


@pytest.mark.parametrize("changed", ["missing", "foreign", "worker", "ref", "files"])
def test_pending_release_requires_live_custody_and_unchanged_evidence(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, changed: str,
) -> None:
    c = execution_case
    saved = pending(c, monkeypatch)
    if changed == "missing":
        c.con.execute("DELETE FROM reservation")
    elif changed == "foreign":
        c.con.execute("UPDATE reservation SET attempt_id='new-owner'")
    elif changed == "worker":
        c.gone = False
    elif changed == "ref":
        c.ports.repo.update_ref(saved.ref, c.record.base, expected=saved.commit)
    else:
        c.slot.write_file("late", "preserve newer work")
    c.restart()
    monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_kwargs: pytest.fail("pending release changed"))
    assert not isinstance(c.resume(), Terminal)
    assert c.ports.store.completed(c.record.key) is None and head(c.slot) == c.record.request.checked


@pytest.mark.parametrize("changed", ["token", "key_generation", "slot_generation", "path", "foreign", "save"])
def test_stale_release_changes_neither_record_nor_reservations(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, changed: str,
) -> None:
    c = execution_case
    saved = pending(c, monkeypatch, parked=True)
    key = c.record.key
    assert saved.release is not None
    updated = saved.model_copy(update={"release": saved.release.model_copy(update={"phase": ReleasePhase.COMPLETE})})
    if changed == "token":
        key = AttemptKey(key.attempt_id, "foreign", key.reservation_generation)
    elif changed == "key_generation":
        key = AttemptKey(key.attempt_id, key.dispatch_token, key.reservation_generation + 1)
    elif changed == "slot_generation":
        c.con.execute("UPDATE slot SET generation=generation+1 WHERE name=?", (c.record.slot,))
    elif changed == "path":
        c.con.execute("UPDATE slot SET path='/foreign' WHERE name=?", (c.record.slot,))
    elif changed == "foreign":
        c.con.execute("UPDATE reservation SET attempt_id='foreign'")
    else:
        saved = saved.model_copy(update={"when": saved.when + 1})
        updated = updated.model_copy(update={"when": saved.when})
    before = c.con.execute("SELECT save_data FROM land_conflict").fetchall(), c.con.execute("SELECT * FROM reservation").fetchall()
    with pytest.raises(StoreRefused):
        c.ports.store.release(key, saved, updated)
    assert before == (c.con.execute("SELECT save_data FROM land_conflict").fetchall(),
                      c.con.execute("SELECT * FROM reservation").fetchall())
    assert c.ports.store.completed(c.record.key) is None


def test_ordinary_save_cannot_complete_release(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    c = execution_case
    saved = pending(c, monkeypatch, parked=True)
    assert saved.release is not None
    updated = saved.model_copy(update={"release": saved.release.model_copy(update={"phase": ReleasePhase.COMPLETE})})
    with pytest.raises(StoreRefused):
        c.ports.store.save(c.record.key, saved, updated)
    assert c.ports.store.saved(c.record.key) == saved


def test_completed_replay_after_reuse_has_no_external_access(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = execution_case
    c.disposition, c.edit = Disposition.OWNER, edits
    result = c.resume()
    assert isinstance(result, Terminal)
    c.restart()
    c.con.execute("UPDATE slot SET generation=generation+1,path='/reused' WHERE name=?", (c.record.slot,))
    c.con.execute("INSERT INTO reservation(repo_id,slot,attempt_id,generation) VALUES (?,?,?,?)",
                  (c.record.request.repo_id, c.record.slot, "new-attempt", c.record.key.reservation_generation + 1))
    c.slot.write_file("new-owner", "keep new slot bytes")

    def forbidden(*_args: object, **_kwargs: object) -> Never:
        pytest.fail("historical replay touched current work")

    monkeypatch.setattr("taskloop.land_conflict.execute.landing", forbidden)
    monkeypatch.setattr(ConflictStore, "load", forbidden)
    monkeypatch.setattr(ConflictStore, "release", forbidden)
    monkeypatch.setattr(FakeRepo, "identity", forbidden)
    monkeypatch.setattr(type(c.ports.merges), "get", forbidden)
    c.ports = replace(c.ports, gone=forbidden, checkouts=forbidden, run=forbidden)
    assert c.resume() == result and c.slot.read_file("new-owner") == "keep new slot bytes"
    assert c.con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (
        "new-attempt", c.record.key.reservation_generation + 1)
    key = c.record.key
    assert c.ports.store.completed(AttemptKey(key.attempt_id, "forged", key.reservation_generation)) is None
    assert c.ports.store.completed(AttemptKey(key.attempt_id, key.dispatch_token, key.reservation_generation + 1)) is None
