"""Conflict preservation retains bytes and adopts interrupted effects after reopening the database."""

from collections.abc import Callable, Generator, Sequence
from dataclasses import replace
from pathlib import Path

import land_conflict_bench
import pytest
from doubles import FakeSlotFiles
from git_porcelain import EmbeddedRepositories, GitUnavailable, RefMoved, Sha
from git_porcelain.testing import FakeRepo, FakeWorktree
from land_conflict_bench import ExecutionCase
from merge_bench import head

from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.land_conflict.models import Save, SavePhase
from taskloop.land_conflict.store import ConflictStore
from taskloop.merge.models import Completed, Disposition, InProgress, Phase, Reason, Terminal, Unavailable
from taskloop.wip import is_saved


@pytest.fixture
def repo(tmp_path: Path) -> FakeRepo:
    return land_conflict_bench.execution_repo(tmp_path)


@pytest.fixture
def execution_case(on_slot: Path, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path) -> Generator[ExecutionCase]:
    yield from land_conflict_bench.execution_case(on_slot, repo, slot, tmp_path)


def saved(c: ExecutionCase) -> Save:
    result = c.ports.store.saved(c.record.key)
    assert result is not None and result.phase is SavePhase.COMPLETE and result.commit is not None
    assert c.con.execute("SELECT count(*) FROM land_conflict WHERE save_data IS NOT NULL").fetchone() == (1,)
    assert dict(c.ports.repo.branches("task/")) == {"task/tl-1": c.record.request.checked}
    assert c.con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (
        c.record.key.attempt_id, c.record.key.reservation_generation)
    assert c.slot.branch() is None
    assert [ref.sha for ref in c.ports.repo.refs([result.ref]) if ref.name == result.ref] == [result.commit]
    return result


@pytest.mark.parametrize("delete", [False, True])
def test_unfinished_bytes_deletions_and_both_inputs_are_retained(execution_case: ExecutionCase, delete: bool) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER

    def edit(slot: FakeWorktree) -> None:
        slot.write_file("staged", "indexed version\n")
        slot.stage(("staged",))
        slot.write_file("staged", "working version wins\n")
        slot.write_file("new", "untracked bytes\n")
        slot.write_file(".gitignore", "ignored\n")
        slot.write_file("ignored", "local data\n")
        if delete:
            slot.remove_file("README")
        else:
            markers = slot.read_file("README")
            assert markers is not None and "<<<<<<<" in markers
            slot.write_file("README", markers + "partially edited\n")

    c.edit = edit
    result = c.resume()
    assert isinstance(result, Terminal) and result.reason is Reason.OWNER
    record = saved(c)
    tree = c.ports.repo.tree(record.commit or "")
    assert tree is not None and is_saved(c.ports.repo, record.commit or "")
    readme = tree.read("README")
    assert readme is None if delete else readme is not None and readme.endswith(b"partially edited\n")
    assert tree.read("staged") == b"working version wins\n" and tree.read("new") == b"untracked bytes\n"
    assert "ignored" not in tree.files and c.slot.read_file("ignored") == "local data\n"
    assert {c.record.request.checked, c.record.request.target, record.head} <= {
        str(entry.sha) for entry in c.ports.repo.history([record.commit or ""])}
    assert f"Task-Loop-Merge-Start: {record.source}" in record.message
    assert f"Task-Loop-Merge-Target: {record.target}" in record.message
    assert head(c.slot) == record.head and not c.slot.merging() and c.calls == 1
    c.restart()
    assert isinstance(c.resume(), Terminal) and saved(c) == record and c.calls == 1


@pytest.fixture
def automatic_case(on_slot: Path, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path) -> Generator[ExecutionCase]:
    def edit(author: FakeWorktree) -> None:
        author.write_file("automatic", "other side\n")

    yield from land_conflict_bench.execution_case(on_slot, repo, slot, tmp_path, edit)


def test_automatic_merge_changes_survive(automatic_case: ExecutionCase) -> None:
    c = automatic_case
    c.disposition = Disposition.OWNER
    assert isinstance(c.resume(), Terminal)
    tree = c.ports.repo.tree(saved(c).commit or "")
    assert tree is not None and tree.read("automatic") == b"other side\n"


def test_completed_result_is_retained_directly(execution_case: ExecutionCase) -> None:
    c = execution_case
    result = c.resume()
    assert isinstance(result, Completed)
    record = saved(c)
    assert record.accepted and record.commit == result.commit and record.head == result.commit
    assert not is_saved(c.ports.repo, result.commit) and not c.slot.merging()
    c.restart()
    assert c.resume() == result and saved(c) == record and c.calls == 1


def interrupt_at(c: ExecutionCase, monkeypatch: pytest.MonkeyPatch, boundary: str, after: bool) -> None:
    if boundary == "intent" or boundary in ("object", "ref", "complete"):
        owner, method = ConflictStore, "save"
    elif boundary in ("stage", "capture"):
        owner, method = FakeWorktree, boundary
    else:
        owner, method = FakeRepo, boundary
    original: Callable[..., object] = getattr(owner, method)
    fired = False

    def interrupted(self: object, *args: object, **kwargs: object) -> object:
        nonlocal fired
        record = c.ports.store.saved(c.record.key)
        eligible = record is not None
        if method == "save":
            phase = SavePhase.CAPTURE.value if boundary == "intent" else boundary
            eligible = len(args) == 3 and isinstance(args[2], Save) and args[2].phase.value == phase
        elif method == "capture":
            eligible = record is not None and record.phase is SavePhase.CAPTURE
        if eligible and not fired:
            fired = True
            assert not c.con.in_transaction
            if after:
                original(self, *args, **kwargs)
            raise KeyboardInterrupt
        return original(self, *args, **kwargs)

    monkeypatch.setattr(owner, method, interrupted)


@pytest.mark.parametrize("boundary", ["intent", "capture", "object", "ref", "complete", "stage", "commit_tree", "update_ref"])
@pytest.mark.parametrize("after", [False, True])
def test_interrupted_saves_reconcile_without_duplicate_effects(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, boundary: str, after: bool,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    made: list[Sha] = []
    commit_tree = FakeRepo.commit_tree

    def create(self: FakeRepo, tree: str, parents: Sequence[str], message: str, *, when: int | None = None) -> Sha:
        commit = commit_tree(self, tree, parents, message, when=when)
        made.append(commit)
        return commit

    monkeypatch.setattr(FakeRepo, "commit_tree", create)
    # Keep one unresolved entry until preservation, rather than the merge engine's earlier baseline capture.
    if boundary == "stage":
        c.interrupt = True
        with pytest.raises(KeyboardInterrupt):
            c.resume()
        work = c.ports.merges.get(c.record.key.attempt_id)
        assert work is not None
        c.ports.merges.put(work, work.model_copy(update={"phase": Phase.TERMINAL, "reason": Reason.OWNER}))
        # The baseline stage cleared the conflict; reestablish the same owned merge and its unresolved index.
        c.slot.abort_merge()
        c.slot.start_merge(c.record.request.target)
    with monkeypatch.context() as patch:
        interrupt_at(c, patch, boundary, after)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    before = c.ports.store.saved(c.record.key)
    refs = dict(c.ports.repo.branches("task-loop/conflicts/"))
    c.restart()
    c.ports = replace(c.ports, clock=lambda: 200)
    assert isinstance(c.resume(), Terminal)
    record = saved(c)
    if before is not None:
        assert record.when == before.when
        if before.commit is not None:
            assert record.commit == before.commit
    if refs:
        assert dict(c.ports.repo.branches("task-loop/conflicts/")) == refs
    assert c.calls == 1
    c.restart()
    assert isinstance(c.resume(), Terminal) and saved(c) == record and c.calls == 1
    own = [entry for entry in c.ports.repo.history([record.commit or ""]) if is_saved(c.ports.repo, str(entry.sha))]
    assert len(own) == 1
    assert made and set(made) == {record.commit}


@pytest.mark.parametrize("after", [False, True])
def test_completed_ref_reconciles_after_interruption(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, after: bool,
) -> None:
    c = execution_case
    with monkeypatch.context() as patch:
        interrupt_at(c, patch, "update_ref", after)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    original_head = head(c.slot)
    c.restart()
    result = c.resume()
    assert isinstance(result, Completed) and result.commit == original_head == saved(c).commit and c.calls == 1


@pytest.mark.parametrize("error", [GitUnavailable, EmbeddedRepositories, StoreUnavailable])
def test_unavailable_capture_keeps_original_reason_and_retries(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, error: type[Exception],
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    with monkeypatch.context() as patch:
        interrupt_at(c, patch, "object", False)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    before = c.slot.read_file("README")

    def fail(*_args: object, **_kwargs: object) -> None:
        if error is EmbeddedRepositories:
            raise EmbeddedRepositories("capture is unavailable", ("nested",))
        raise error("capture is unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(FakeWorktree, "capture", fail)
        result = c.resume()
        assert isinstance(result, Unavailable) and result.explanation
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None and work.reason is Reason.OWNER and c.slot.read_file("README") == before
    c.restart()
    assert isinstance(c.resume(), Terminal) and saved(c) and c.calls == 1


@pytest.mark.parametrize("changed", ["ref", "files", "head", "merge", "reservation", "worker"])
def test_changed_work_cannot_replace_a_pending_save(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, changed: str,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    with monkeypatch.context() as patch:
        interrupt_at(c, patch, "ref", True)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    record = c.ports.store.saved(c.record.key)
    assert record is not None
    if changed == "ref":
        c.ports.repo.update_ref(record.ref, c.record.request.target, expected=None)
    elif changed == "files":
        c.slot.write_file("later", "new unrecorded edit")
    elif changed == "head":
        c.slot.abort_merge()
        c.slot.park(c.record.request.target)
    elif changed == "merge":
        assert isinstance(c.ports.files, FakeSlotFiles)
        c.ports.files.contents[record.gitdir / "MERGE_HEAD"] = ("f" * 40 + "\n").encode()
    elif changed == "reservation":
        c.con.execute("UPDATE slot SET generation=generation+1")
    else:
        c.gone = False
    c.restart()
    result = c.resume()
    assert isinstance(result, (Unavailable, Terminal, InProgress)) and result.explanation and c.calls == 1
    assert c.con.execute("SELECT count(*) FROM reservation").fetchone() == (1,)
    if changed != "reservation":
        assert c.ports.store.saved(c.record.key) == record


def test_completed_save_never_absorbs_later_edits(execution_case: ExecutionCase) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    assert isinstance(c.resume(), Terminal)
    record = saved(c)
    c.slot.write_file("later", "keep this work")
    c.restart()
    result = c.resume()
    assert isinstance(result, Unavailable) and result.explanation and c.slot.read_file("later") == "keep this work"
    assert saved(c) == record and c.calls == 1


@pytest.mark.parametrize("reason", [Reason.EXPIRED, Reason.UNSUPPORTED, Reason.EXHAUSTED])
def test_owned_terminal_outcomes_preserve_before_returning(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, reason: Reason,
) -> None:
    c = execution_case
    if reason is Reason.EXPIRED:
        c.ports = replace(c.ports, clock=lambda: 301)
    elif reason is Reason.UNSUPPORTED:
        monkeypatch.setattr("taskloop.merge.git.supported", lambda _repo, _work: False)
    else:
        c.disposition = Disposition.INCOMPLETE
        for _ in range(2):
            assert isinstance(c.resume(), InProgress)
    result = c.resume()
    assert isinstance(result, Terminal) and result.reason is reason
    record = saved(c)
    assert not record.accepted
    assert {record.source, record.target, record.head} <= {
        str(entry.sha) for entry in c.ports.repo.history([record.commit or ""])}
    assert c.calls == (3 if reason is Reason.EXHAUSTED else 0)


def test_ref_contention_is_retryable_without_another_resolution(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    with monkeypatch.context() as patch:
        patch.setattr(FakeRepo, "update_ref", lambda *_args, **_kwargs: RefMoved(None))
        result = c.resume()
    assert isinstance(result, Unavailable) and result.explanation
    pending = c.ports.store.saved(c.record.key)
    assert pending is not None and pending.phase is SavePhase.REF
    c.restart()
    assert isinstance(c.resume(), Terminal) and saved(c).commit == pending.commit and c.calls == 1


def test_foreign_ref_during_initial_intent_is_never_overwritten(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    original = ConflictStore.save

    def claim(self: ConflictStore, key: object, previous: Save | None, updated: Save) -> Save:
        if previous is None:
            c.ports.repo.update_ref(updated.ref, c.record.request.target, expected=None)
        return original(self, updated.key, previous, updated)

    with monkeypatch.context() as patch:
        patch.setattr(ConflictStore, "save", claim)
        result = c.resume()
    assert isinstance(result, Unavailable) and result.reason is Reason.MOVED and result.explanation
    record = c.ports.store.saved(c.record.key)
    assert record is not None and record.phase is SavePhase.CAPTURE
    assert [ref.sha for ref in c.ports.repo.refs([record.ref])] == [c.record.request.target]
    assert c.calls == 1 and c.slot.merging()


def test_ownership_loss_after_ref_write_cannot_record_completion(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    original = FakeRepo.update_ref

    def revoke(self: FakeRepo, ref: str, sha: str, *, expected: str | None = None) -> object:
        result = original(self, ref, sha, expected=expected)
        c.con.execute("UPDATE slot SET generation=generation+1")
        return result

    monkeypatch.setattr(FakeRepo, "update_ref", revoke)
    result = c.resume()
    assert isinstance(result, Unavailable) and result.explanation
    row = c.con.execute("SELECT save_data FROM land_conflict").fetchone()
    record = Save.model_validate_json(row[0])
    assert record.phase is SavePhase.REF and c.calls == 1
    assert [ref.sha for ref in c.ports.repo.refs([record.ref])] == [record.commit]
    assert c.con.execute("SELECT count(*) FROM reservation").fetchone() == (1,)


def test_stale_save_write_cannot_replace_completed_work(execution_case: ExecutionCase) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    assert isinstance(c.resume(), Terminal)
    record = saved(c)
    with pytest.raises(StoreRefused):
        c.ports.store.save(c.record.key, None, record)
    with pytest.raises(StoreRefused):
        c.ports.store.save(c.record.key, record, record.model_copy(update={"tree": c.record.request.target}))
    assert saved(c) == record


def test_work_arriving_during_ref_publication_stays_reserved(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    original = FakeRepo.update_ref

    def edit(self: FakeRepo, ref: str, sha: str, *, expected: str | None = None) -> object:
        result = original(self, ref, sha, expected=expected)
        c.slot.write_file("late", "work arriving during save")
        return result

    monkeypatch.setattr(FakeRepo, "update_ref", edit)
    result = c.resume()
    assert isinstance(result, Unavailable) and result.explanation
    record = saved(c)
    tree = c.ports.repo.tree(record.commit or "")
    assert tree is not None and "late" not in tree.files
    assert c.slot.read_file("late") == "work arriving during save" and c.calls == 1


def test_pending_save_prevents_another_resolution_if_merge_progress_changes(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    with monkeypatch.context() as patch:
        interrupt_at(c, patch, "object", False)
        with pytest.raises(KeyboardInterrupt):
            c.resume()
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None
    c.ports.merges.put(work, work.model_copy(update={"phase": Phase.RESOLVE}))
    c.restart()
    result = c.resume()
    assert isinstance(result, Unavailable) and result.explanation and c.calls == 1


def test_git_effects_run_outside_write_transactions(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    seen: set[str] = set()

    def observe(owner: type[FakeRepo] | type[FakeWorktree], method: str) -> None:
        original: Callable[..., object] = getattr(owner, method)

        def checked(self: object, *args: object, **kwargs: object) -> object:
            assert not c.con.in_transaction
            result = original(self, *args, **kwargs)
            assert not c.con.in_transaction
            seen.add(method)
            return result

        monkeypatch.setattr(owner, method, checked)

    for method in ("stage", "capture"):
        observe(FakeWorktree, method)
    for method in ("commit_tree", "update_ref"):
        observe(FakeRepo, method)
    assert isinstance(c.resume(), Terminal) and saved(c)
    assert seen == {"stage", "capture", "commit_tree", "update_ref"}
