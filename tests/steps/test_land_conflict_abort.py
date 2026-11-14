"""Intact-database restart adopts only the recorded checkout after an abort."""

from collections.abc import Generator
from dataclasses import replace
from pathlib import Path

import land_conflict_bench
import pytest
from doubles import FakeSlotFiles
from git_porcelain import GitUnavailable
from git_porcelain.testing import FakeRepo, FakeWorktree
from land_conflict_bench import ExecutionCase
from merge_bench import head

from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_types import AttemptKey
from taskloop.land_conflict.abort_models import AbortPhase
from taskloop.land_conflict.models import Save
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Completed, Disposition, InProgress, Reason, Terminal, Unavailable


@pytest.fixture
def repo(tmp_path: Path) -> FakeRepo:
    return land_conflict_bench.execution_repo(tmp_path)


@pytest.fixture
def execution_case(on_slot: Path, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path) -> Generator[ExecutionCase]:
    yield from land_conflict_bench.execution_case(on_slot, repo, slot, tmp_path)


def edit(slot: FakeWorktree) -> None:
    slot.write_file("README", "staged conflict edit\n")
    slot.stage(("README",))
    slot.write_file("README", "working conflict edit\n")
    slot.write_file("addition", "new staged bytes\n")
    slot.stage(("addition",))
    slot.write_file("addition", "working addition bytes\n")
    slot.write_file("notes/local", "untracked bytes\n")
    slot.write_file(".gitignore", "ignored\n")
    slot.write_file("ignored", "ignored local data\n")


def retained(c: ExecutionCase) -> Save:
    completed = c.ports.store.completed(c.record.key)
    saved = completed or c.ports.store.saved(c.record.key)
    assert saved is not None and saved.abort is not None
    assert c.con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (
        None if completed else (c.record.key.attempt_id, c.record.key.reservation_generation))
    assert dict(c.ports.repo.branches("task/")) == {"task/tl-1": c.record.request.checked}
    assert dict(c.ports.repo.branches("task-loop/conflicts/")) == {saved.ref.removeprefix("refs/heads/"): saved.commit}
    return saved


def interrupt(c: ExecutionCase, patch: pytest.MonkeyPatch, boundary: str) -> list[bool]:
    calls: list[bool] = []
    abort_merge = FakeWorktree.abort_merge
    save = ConflictStore.save

    def abort(self: FakeWorktree) -> None:
        assert not c.con.in_transaction
        calls.append(True)
        if boundary == "before":
            raise KeyboardInterrupt
        abort_merge(self)
        if boundary == "after":
            raise KeyboardInterrupt

    def put(self: ConflictStore, key: AttemptKey, previous: Save | None, updated: Save) -> Save:
        result = save(self, key, previous, updated)
        if boundary == "complete" and updated.abort is not None and updated.abort.phase is AbortPhase.COMPLETE:
            assert not c.con.in_transaction
            raise KeyboardInterrupt
        return result

    patch.setattr(FakeWorktree, "abort_merge", abort)
    patch.setattr(ConflictStore, "save", put)
    return calls


@pytest.mark.parametrize("boundary", ["before", "after", "complete"])
@pytest.mark.parametrize("delete", [False, True])
def test_abort_restart_retains_bytes_and_exact_custody(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, boundary: str, delete: bool,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER

    def edits(slot: FakeWorktree) -> None:
        edit(slot)
        if delete:
            slot.remove_file("README")

    c.edit = edits
    with monkeypatch.context() as patch:
        calls = interrupt(c, patch, boundary)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    saved = retained(c)
    assert calls == [True] and saved.abort is not None
    assert ("notes/local", ("100644", saved.abort.before.files["notes/local"][1])) in saved.abort.after.files.items()
    tree = c.ports.repo.tree(saved.commit or "")
    assert tree is not None
    assert tree.read("README") == (None if delete else b"working conflict edit\n")
    assert tree.read("addition") == b"working addition bytes\n" and tree.read("notes/local") == b"untracked bytes\n"
    assert "ignored" not in tree.files
    parents = tuple(c.ports.repo.tree(f"{saved.commit}^{i}") for i in range(1, len(saved.parents) + 1))
    assert tuple(str(parent.sha) for parent in parents if parent is not None) == saved.parents
    c.restart()
    aborts: list[bool] = []
    abort_merge = FakeWorktree.abort_merge

    def count(self: FakeWorktree) -> None:
        aborts.append(True)
        abort_merge(self)

    monkeypatch.setattr(FakeWorktree, "abort_merge", count)
    result = c.resume()
    assert isinstance(result, Terminal) and result.reason is Reason.OWNER and result.explanation == "Retain both sides."
    complete = retained(c)
    assert complete.abort is not None and complete.abort.phase is AbortPhase.COMPLETE
    assert complete.model_dump(exclude={"abort", "cleanup", "release"}) == saved.model_dump(exclude={"abort", "cleanup", "release"})
    assert aborts == ([True] if boundary == "before" else []) and c.calls == 1
    assert not c.slot.merging() and head(c.slot) == c.record.base
    assert c.slot.read_file("notes/local") is None and c.slot.read_file("ignored") == "ignored local data\n"
    assert c.slot.read_file("addition") is None
    source = c.ports.repo.tree(c.record.base)
    assert source is not None and source.read("README") == (c.slot.read_file("README") or "").encode()
    c.restart()
    assert c.resume() == result and retained(c) == complete and c.calls == 1


def change_checkout(c: ExecutionCase, saved: Save, changed: str) -> None:
    if changed in ("head", "branch"):
        # This is an owner mutation in the semantic fake, outside factory reconciliation.
        c.slot.abort_merge()
        if changed == "head":
            c.slot.park(c.record.request.target)
        else:
            c.slot.checkout_new("foreign", c.record.request.checked)
    elif changed == "merge":
        assert isinstance(c.ports.files, FakeSlotFiles)
        c.ports.files.contents[saved.gitdir / "MERGE_HEAD"] = ("f" * 40 + "\n").encode()
    elif changed == "index":
        c.slot.stage(("notes/local",))
    elif changed in ("tracked", "untracked_bytes", "ignored"):
        path = {"tracked": "README", "untracked_bytes": "notes/local", "ignored": "ignored"}[changed]
        c.slot.write_file(path, "foreign bytes\n")
    elif changed == "untracked_name":
        c.slot.remove_file("notes/local")
        c.slot.write_file("notes/other", "untracked bytes\n")
    elif changed == "gitdir":
        assert isinstance(c.ports.files, FakeSlotFiles)
        c.ports.files.contents[c.slot.path / ".git"] = b"gitdir: /foreign/worktrees/s1\n"
    else:
        c.ports.repo.update_ref(saved.ref, c.record.request.target, expected=saved.commit)


def change_ownership(c: ExecutionCase, changed: str) -> None:
    if changed == "repo":
        c.ports = replace(c.ports, repo=land_conflict_bench.execution_repo(c.slot.path.parent / "foreign"))
    elif changed == "token":
        c.con.execute("UPDATE land_conflict SET dispatch_token='foreign', data=json_set(data,'$.key.dispatch_token','foreign')")
    elif changed == "generation":
        c.con.execute("UPDATE reservation SET generation=generation+1")
    elif changed == "path":
        c.con.execute("UPDATE slot SET path='/foreign'")
    elif changed == "worker":
        work = c.ports.merges.get(c.record.key.attempt_id)
        assert work is not None and work.executions[0].worker is not None
        worker = work.executions[0].worker.model_copy(update={"start": "foreign"})
        execution = work.executions[0].model_copy(update={"worker": worker})
        c.ports.merges.put(work, work.model_copy(update={"executions": (execution,)}))
    else:
        c.gone = False


@pytest.mark.parametrize("changed", [
    "head", "branch", "merge", "index", "tracked", "untracked_bytes", "untracked_name", "ignored", "gitdir", "repo",
    "token", "generation", "path", "worker", "live", "ref",
])
@pytest.mark.parametrize("boundary", ["before", "after", "complete"])
def test_changed_abort_expectations_are_never_adopted(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, changed: str, boundary: str,
) -> None:
    c = execution_case
    c.disposition, c.edit = Disposition.OWNER, edit
    with monkeypatch.context() as patch:
        interrupt(c, patch, boundary)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    saved = retained(c)
    if changed in ("repo", "token", "generation", "path", "worker", "live"):
        change_ownership(c, changed)
    else:
        change_checkout(c, saved, changed)
    before = c.con.execute("SELECT save_data FROM land_conflict").fetchone()
    reservation = c.con.execute("SELECT * FROM reservation").fetchall()
    c.restart()
    aborts: list[bool] = []
    monkeypatch.setattr(FakeWorktree, "abort_merge", lambda _self: aborts.append(True))
    result = c.resume()
    assert isinstance(result, (Unavailable, InProgress)) and result.explanation
    assert not aborts and c.calls == 1
    assert c.con.execute("SELECT save_data FROM land_conflict").fetchone() == before
    assert c.con.execute("SELECT * FROM reservation").fetchall() == reservation


def test_abort_failure_leaves_pending_intent(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    c = execution_case
    c.disposition, c.edit = Disposition.OWNER, edit

    def fail(_self: FakeWorktree) -> None:
        raise GitUnavailable("abort failed")

    with monkeypatch.context() as patch:
        patch.setattr(FakeWorktree, "abort_merge", fail)
        result = c.resume()
    assert isinstance(result, Unavailable) and "abort failed" in result.explanation
    saved = retained(c)
    assert saved.abort is not None and saved.abort.phase is AbortPhase.PENDING and c.slot.merging()
    c.restart()
    assert isinstance(c.resume(), Terminal) and c.calls == 1


@pytest.mark.parametrize("boundary", ["capture", "update_ref"])
def test_preservation_failure_prevents_abort(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, boundary: str,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER

    def fail(*_args: object, **_kwargs: object) -> None:
        raise GitUnavailable("save failed")

    owner = FakeWorktree if boundary == "capture" else FakeRepo
    monkeypatch.setattr(owner, boundary, fail)
    monkeypatch.setattr(FakeWorktree, "abort_merge", lambda _self: pytest.fail("abort before preservation"))
    assert isinstance(c.resume(), Unavailable) and c.slot.merging()


def test_accepted_result_bypasses_abort(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    c = execution_case
    monkeypatch.setattr(FakeWorktree, "abort_merge", lambda _self: pytest.fail("abort of accepted result"))
    result = c.resume()
    assert isinstance(result, Completed)
    saved = c.ports.store.saved(c.record.key)
    assert saved is not None and saved.abort is None
    c.restart()
    assert c.resume() == result


def test_abort_store_transitions_cannot_change_preservation(execution_case: ExecutionCase) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    assert isinstance(c.resume(), Terminal)
    saved = retained(c)
    assert saved.abort is not None
    pending = saved.abort.model_copy(update={"phase": AbortPhase.PENDING})
    for changes in ({"abort": None}, {"abort": pending}, {"tree": c.record.request.target}):
        with pytest.raises((StoreRefused, ValueError)):
            c.ports.store.save(c.record.key, saved, saved.model_copy(update=changes))
