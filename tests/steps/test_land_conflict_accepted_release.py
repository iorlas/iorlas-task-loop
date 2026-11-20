"""Accepted resolution custody survives interruptions without revisiting resolution or new slot owners."""

from collections.abc import Generator, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Never

import land_conflict_bench
import pytest
from doubles import FakeSlotFiles
from git_porcelain import Recorded, Sha
from git_porcelain.testing import FakeRepo, FakeWorktree
from land_conflict_bench import ExecutionCase
from merge_bench import head
from pydantic import ValidationError

from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_types import AttemptKey
from taskloop.land_conflict.cleanup_models import CleanupPhase
from taskloop.land_conflict.models import Save, SavePhase
from taskloop.land_conflict.release_models import Release, ReleasePhase
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Completed, Phase, Unavailable
from taskloop.merge.start import Merge


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

    def target_edit(wt: FakeWorktree) -> None:
        wt.remove_file("base-only")
        wt.write_file(".gitignore", "ignored\n")

    for case in land_conflict_bench.execution_case(on_slot, repo, slot, tmp_path, target_edit):
        case.edit = lambda wt: wt.write_file("ignored", "ignored bytes\n")
        yield case


def test_accepted_commit_remains_reachable_after_independent_base_release(execution_case: ExecutionCase) -> None:
    c = execution_case
    branches = dict(c.ports.repo.branches("task/"))
    result = c.resume()
    assert isinstance(result, Completed)
    saved = c.ports.store.completed(c.record.key)
    assert saved is not None and saved.cleanup is not None and saved.release is not None
    assert saved.accepted and saved.commit == saved.head == result.commit
    assert saved.abort is None
    assert saved.cleanup.after.head == result.commit
    assert saved.release.result == result and saved.release.phase is ReleasePhase.COMPLETE
    assert c.record.base not in (result.commit, result.source, result.target)
    assert head(c.slot) == c.record.base and c.slot.branch() is None and not c.slot.merging()
    assert c.slot.read_file("README") == "admitted base\n" and c.slot.read_file("base-only") == "base bytes\n"
    assert c.slot.read_file("ignored") == "ignored bytes\n"
    assert "ignored" in c.slot.dirty(ignored_under=(".",)).ignored
    assert not c.slot.dirty().raw
    tree = c.ports.repo.tree(saved.ref)
    assert tree is not None and str(tree.sha) == result.commit and tree.read("README") == b"X\ncurrent main\n"
    assert dict(c.ports.repo.branches("task/")) == branches
    assert c.con.execute("SELECT count(*) FROM reservation").fetchone() == (0,)
    assert c.con.execute("SELECT count(*) FROM attempt").fetchone() == (1,)


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("boundary", ["capture", "object", "ref", "saved", "exclude", "cleanup", "cleaned", "release", "released"])
def test_accepted_save_cleanup_and_release_restart_at_every_write(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, boundary: str, after: bool,
) -> None:
    c = execution_case
    save, release = ConflictStore.save, ConflictStore.release

    def put(self: ConflictStore, key: AttemptKey, previous: Save | None, updated: Save) -> Save:
        assert not c.con.in_transaction
        selected = ((updated.cleanup is None and updated.phase is {
            "capture": SavePhase.CAPTURE, "object": SavePhase.OBJECT, "ref": SavePhase.REF, "saved": SavePhase.COMPLETE,
        }.get(boundary)) or (updated.cleanup is not None and updated.release is None and updated.cleanup.phase is {
            "exclude": CleanupPhase.EXCLUDE, "cleanup": CleanupPhase.PARK, "cleaned": CleanupPhase.COMPLETE,
        }.get(boundary)) or (boundary == "release" and updated.release is not None))
        if selected and not after:
            raise KeyboardInterrupt
        value = save(self, key, previous, updated)
        if selected:
            raise KeyboardInterrupt
        return value

    def releasing(self: ConflictStore, key: AttemptKey, previous: Save, updated: Save) -> Save:
        assert not c.con.in_transaction
        if not after:
            raise KeyboardInterrupt
        release(self, key, previous, updated)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(ConflictStore, "release" if boundary == "released" else "save", releasing if boundary == "released" else put)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    pending = c.ports.store.completed(c.record.key) or c.ports.store.saved(c.record.key)
    c.restart()
    if pending is not None:
        monkeypatch.setattr(Merge, "resume", lambda *_args: pytest.fail("resolution repeated after durable save"))
    result = c.resume()
    assert isinstance(result, Completed) and c.calls == 1
    completed = c.ports.store.completed(c.record.key)
    assert completed is not None and completed.release is not None and completed.release.result == result
    if pending is not None:
        assert completed.head == pending.head
    assert head(c.slot) == c.record.base and c.slot.read_file("ignored") == "ignored bytes\n"
    assert c.con.execute("SELECT count(*) FROM reservation").fetchone() == (0,)


def pending_release(c: ExecutionCase, patch: pytest.MonkeyPatch) -> Save:
    save = ConflictStore.save

    def put(self: ConflictStore, key: AttemptKey, previous: Save | None, updated: Save) -> Save:
        value = save(self, key, previous, updated)
        if updated.release is not None:
            raise KeyboardInterrupt
        return value

    with patch.context() as context:
        context.setattr(ConflictStore, "save", put)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    saved = c.ports.store.saved(c.record.key)
    assert saved is not None and saved.release is not None and saved.release.phase is ReleasePhase.PENDING
    return saved


@pytest.mark.parametrize("after", [False, True])
def test_accepted_ignored_protection_resumes_after_interruption(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, after: bool,
) -> None:
    c = execution_case
    exclude = FakeWorktree.exclude

    def excluding(self: FakeWorktree, patterns: Sequence[str]) -> None:
        assert not c.con.in_transaction
        if c.calls == 1 and not after:
            raise KeyboardInterrupt
        exclude(self, patterns)
        if c.calls == 1:
            raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(FakeWorktree, "exclude", excluding)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    saved = c.ports.store.saved(c.record.key)
    assert saved is not None and saved.cleanup is not None and saved.cleanup.phase is CleanupPhase.EXCLUDE
    c.restart()
    monkeypatch.setattr(Merge, "resume", lambda *_args: pytest.fail("resolution repeated during cleanup"))
    result = c.resume()
    assert isinstance(result, Completed) and result.commit == saved.commit and c.calls == 1
    assert c.slot.read_file("ignored") == "ignored bytes\n" and head(c.slot) == c.record.base


@pytest.mark.parametrize("after", [False, True])
def test_accepted_parking_adopts_observed_effect(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, after: bool,
) -> None:
    c = execution_case
    saved = pending_release(c, monkeypatch)
    park = FakeWorktree.park
    calls: list[str] = []

    def parking(self: FakeWorktree, base: str, *, clean_keep: Sequence[str] | None = None, keep_ignored: bool = False) -> Sha:
        assert not c.con.in_transaction and clean_keep == () and keep_ignored
        calls.append(base)
        if not after:
            raise KeyboardInterrupt
        park(self, base, clean_keep=clean_keep, keep_ignored=keep_ignored)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(FakeWorktree, "park", parking)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    assert calls == [c.record.base]
    c.restart()
    if after:
        monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_kwargs: pytest.fail("completed parking repeated"))
    assert saved.release is not None and c.resume() == saved.release.result and c.calls == 1
    assert c.slot.read_file("ignored") == "ignored bytes\n"


def test_accepted_release_transaction_rolls_back_and_preserves_other_custody(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = execution_case
    saved = pending_release(c, monkeypatch)
    c.con.execute("INSERT INTO slot(repo_id,name,path,generation) VALUES (?,'other','/other',7)", (c.record.request.repo_id,))
    c.con.execute("INSERT INTO reservation(repo_id,slot,attempt_id,generation) VALUES (?,'other','other-attempt',7)",
                  (c.record.request.repo_id,))
    c.con.execute("CREATE TEMP TRIGGER refuse_release BEFORE DELETE ON reservation BEGIN SELECT RAISE(ABORT,'stop'); END")
    result = c.resume()
    assert isinstance(result, Unavailable) and result.explanation
    assert c.ports.store.saved(c.record.key) == saved and c.ports.store.completed(c.record.key) is None
    assert c.con.execute("SELECT count(*) FROM reservation").fetchone() == (2,)
    assert head(c.slot) == c.record.base
    c.con.execute("DROP TRIGGER refuse_release")
    c.restart()
    monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_kwargs: pytest.fail("already parked"))
    assert saved.release is not None and c.resume() == saved.release.result
    assert c.con.execute("SELECT slot,attempt_id,generation FROM reservation").fetchall() == [("other", "other-attempt", 7)]


@pytest.mark.parametrize("changed", ["missing", "foreign", "worker", "ref", "files", "ignored", "repository"])
def test_accepted_pending_release_refuses_changed_evidence(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, changed: str,
) -> None:
    c = execution_case
    saved = pending_release(c, monkeypatch)
    if changed == "missing":
        c.con.execute("DELETE FROM reservation")
    elif changed == "foreign":
        c.con.execute("UPDATE reservation SET attempt_id='new-owner'")
    elif changed == "worker":
        c.gone = False
    elif changed == "ref":
        c.ports.repo.update_ref(saved.ref, c.record.base, expected=saved.commit)
    elif changed == "repository":
        assert isinstance(c.ports.files, FakeSlotFiles)
        c.ports.files.contents[c.slot.path / ".git"] = b"gitdir: /foreign/worktrees/s1\n"
    else:
        c.slot.write_file("ignored" if changed == "ignored" else "late", "preserve newer bytes")
    c.restart()
    monkeypatch.setattr(FakeWorktree, "park", lambda *_args, **_kwargs: pytest.fail("changed evidence released"))
    result = c.resume()
    assert not isinstance(result, Completed) and result.explanation and c.calls == 1
    assert c.ports.store.completed(c.record.key) is None and head(c.slot) == saved.head


def test_accepted_replay_after_slot_reuse_reads_only_completion(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = execution_case
    result = c.resume()
    assert isinstance(result, Completed)
    c.restart()
    c.con.execute("UPDATE slot SET generation=generation+1,path='/reused' WHERE name=?", (c.record.slot,))
    c.con.execute("INSERT INTO reservation(repo_id,slot,attempt_id,generation) VALUES (?,?,?,?)",
                  (c.record.request.repo_id, c.record.slot, "new-attempt", c.record.key.reservation_generation + 1))
    c.slot.write_file("new-owner", "keep new bytes")

    def forbidden(*_args: object, **_kwargs: object) -> Never:
        pytest.fail("historical replay touched new work")

    monkeypatch.setattr("taskloop.land_conflict.execute.landing", forbidden)
    monkeypatch.setattr(ConflictStore, "load", forbidden)
    monkeypatch.setattr(ConflictStore, "release", forbidden)
    monkeypatch.setattr(FakeRepo, "identity", forbidden)
    monkeypatch.setattr(type(c.ports.merges), "get", forbidden)
    c.ports = replace(c.ports, gone=forbidden, checkouts=forbidden, run=forbidden)
    assert c.resume() == result and c.slot.read_file("new-owner") == "keep new bytes"
    assert c.con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (
        "new-attempt", c.record.key.reservation_generation + 1)
    key = c.record.key
    assert c.ports.store.completed(AttemptKey(key.attempt_id, "forged", key.reservation_generation)) is None


@pytest.mark.parametrize("field", ["commit", "source", "target", "explanation"])
def test_accepted_release_requires_exact_completed_result(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    c = execution_case
    saved = pending_release(c, monkeypatch)
    assert saved.release is not None
    release = saved.release
    result = release.result.model_copy(update={field: "foreign" if field == "explanation" else "f" * 40})
    with pytest.raises(ValidationError, match="exact completed"):
        Release.model_validate(release.model_dump() | {"result": result.model_dump()})
    work = release.work.model_copy(update={"phase": Phase.TERMINAL})
    with pytest.raises(ValidationError):
        Release.model_validate(release.model_dump() | {"work": work.model_dump()})


def test_accepted_cleanup_cannot_be_rebound_to_different_work(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = execution_case
    saved = pending_release(c, monkeypatch)
    assert saved.cleanup is not None
    cleanup = saved.cleanup
    work = cleanup.work.model_copy(update={"result": "f" * 40})
    with pytest.raises(ValidationError, match="exact clean detached"):
        Save.model_validate(saved.model_dump() | {"cleanup": cleanup.model_copy(update={"work": work}).model_dump(), "release": None})
    assert c.ports.store.saved(c.record.key) == saved
    with pytest.raises(StoreRefused):
        c.ports.store.load(AttemptKey(c.record.key.attempt_id, "forged", c.record.key.reservation_generation))
