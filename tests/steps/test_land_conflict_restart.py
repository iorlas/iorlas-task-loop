"""A detached conflict adopts matching effects and keeps its execution limit across DB reopen."""

from collections.abc import Callable, Generator
from pathlib import Path

import land_conflict_bench
import pytest
from any_agent import RunOutcome
from doubles import FakeSlotFiles
from git_porcelain.testing import FakeRepo, FakeWorktree
from land_conflict_bench import ExecutionCase
from merge_bench import head

from taskloop.attempt_types import AttemptKey, FileRef
from taskloop.evidence_files import EvidenceFiles
from taskloop.merge import git
from taskloop.merge.models import Completed, Disposition, InProgress, Phase, Reason, Terminal, Unavailable, Work
from taskloop.merge.store import MergeStore


@pytest.fixture
def repo(tmp_path: Path) -> FakeRepo:
    return land_conflict_bench.execution_repo(tmp_path)


@pytest.fixture
def execution_case(on_slot: Path, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path) -> Generator[ExecutionCase]:
    yield from land_conflict_bench.execution_case(on_slot, repo, slot, tmp_path)


@pytest.mark.parametrize("action", ["park", "start_merge", "finish_merge"])
def test_restart_adopts_each_completed_effect(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    c = execution_case
    original: Callable[..., object] = getattr(FakeWorktree, action)
    calls = 0

    def interrupted(self: FakeWorktree, *args: object, **kwargs: object) -> object:
        nonlocal calls
        result = original(self, *args, **kwargs)
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt
        return result

    branches = dict(c.ports.repo.branches("task/"))
    monkeypatch.setattr(FakeWorktree, action, interrupted)
    with pytest.raises(KeyboardInterrupt):
        c.resume()
    c.restart()
    monkeypatch.setattr(FakeWorktree, action, original)
    result = c.resume()
    assert isinstance(result, Completed) and c.calls == 1 and c.slot.branch() is None
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None and git.completed(c.ports.repo, result.commit, work)
    assert len([entry for entry in c.ports.repo.history([result.commit]) if "Task-Loop-Merge-Target:" in entry.body]) == 1
    assert dict(c.ports.repo.branches("task/")) == branches


@pytest.mark.parametrize("dirty", [False, True])
def test_start_adopts_only_clean_matching_completed_merge(execution_case: ExecutionCase, dirty: bool) -> None:
    c = execution_case
    assert isinstance(c.resume(), Completed)
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None and work.target is not None
    c.ports.merges.put(work, work.model_copy(update={"phase": Phase.START, "result": None}))
    if dirty:
        c.slot.write_file("foreign", "unrecorded edit")
    c.restart()
    result = c.resume()
    assert isinstance(result, Terminal if dirty else Completed) and c.calls == 1
    assert c.slot.read_file("foreign") == ("unrecorded edit" if dirty else None)


def test_foreign_completed_effect_is_preserved_and_refused(execution_case: ExecutionCase) -> None:
    c = execution_case
    assert isinstance(c.resume(), Completed)
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None
    c.ports.merges.put(work, work.model_copy(update={"phase": Phase.START, "result": None}))
    c.slot.park(work.source)
    c.slot.start_merge(c.record.request.target)
    c.slot.write_file("README", "someone else's resolution\n")
    c.slot.stage(("README",))
    foreign = c.slot.finish_merge("foreign provenance")
    c.restart()
    result = c.resume()
    assert isinstance(result, Terminal) and result.explanation and head(c.slot) == foreign and c.calls == 1


@pytest.mark.parametrize("success", [False, True])
def test_three_executions_are_durable_and_third_can_succeed(execution_case: ExecutionCase, success: bool) -> None:
    c = execution_case
    c.disposition = Disposition.INCOMPLETE
    for _ in range(2):
        assert isinstance(c.resume(), InProgress)
        c.restart()
    if success:
        c.disposition = Disposition.RESOLVED
    result = c.resume()
    assert isinstance(result, Completed if success else Terminal)
    if isinstance(result, Terminal):
        assert result.reason is Reason.EXHAUSTED
    for _ in range(3):
        c.restart()
        assert isinstance(c.resume(), Completed if success else Terminal)
    assert c.calls == 3
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None and [execution.number for execution in work.executions] == [1, 2, 3]
    assert all(execution.worker is not None and execution.input is not None and execution.evidence for execution in work.executions)
    for execution in work.executions:
        assert execution.input is not None
        text = c.ports.evidence.read(FileRef(execution.input.path, execution.input.digest))
        assert "The exact retained requirements." in text


def test_registered_worker_is_never_duplicated_on_restart(execution_case: ExecutionCase) -> None:
    c = execution_case
    c.gone, c.interrupt = False, True
    with pytest.raises(KeyboardInterrupt):
        c.resume()
    c.restart()
    assert c.ports.merges.active_processes()[0].subject == c.record.key.attempt_id
    assert isinstance(c.resume(), InProgress) and c.calls == 1
    c.gone, c.interrupt = True, False
    assert isinstance(c.resume(), InProgress)  # the interrupted execution is consumed
    c.restart()
    assert isinstance(c.resume(), Completed) and c.calls == 2


@pytest.mark.parametrize("after", [False, True])
def test_interrupted_capture_preserves_evidence_or_consumes_the_execution(
    execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch, after: bool,
) -> None:
    c = execution_case
    capture = EvidenceFiles.capture

    def interrupt(self: EvidenceFiles, key: AttemptKey, raw: RunOutcome) -> None:
        if after:
            capture(self, key, raw)
        raise KeyboardInterrupt

    monkeypatch.setattr(EvidenceFiles, "capture", interrupt)
    with pytest.raises(KeyboardInterrupt):
        c.resume()
    c.restart()
    monkeypatch.setattr(EvidenceFiles, "capture", capture)
    assert isinstance(c.resume(), Completed) and c.calls == (1 if after else 2)


def test_unregistered_third_intent_is_reused(execution_case: ExecutionCase, monkeypatch: pytest.MonkeyPatch) -> None:
    c = execution_case
    c.disposition = Disposition.INCOMPLETE
    c.resume()
    c.resume()
    put = MergeStore.put

    def interrupt(self: MergeStore, previous: Work, updated: Work) -> Work:
        work = put(self, previous, updated)
        if len(work.executions) == 3 and work.executions[-1].worker is None:
            raise KeyboardInterrupt
        return work

    monkeypatch.setattr(MergeStore, "put", interrupt)
    with pytest.raises(KeyboardInterrupt):
        c.resume()
    c.restart()
    monkeypatch.setattr(MergeStore, "put", put)
    result = c.resume()
    assert isinstance(result, Terminal) and result.reason is Reason.EXHAUSTED and c.calls == 3


def test_owner_answer_stays_terminal(execution_case: ExecutionCase) -> None:
    c = execution_case
    c.disposition = Disposition.OWNER
    result = c.resume()
    assert isinstance(result, Terminal) and result.reason is Reason.OWNER
    c.restart()
    assert isinstance(c.resume(), Terminal) and c.calls == 1 and c.slot.merging()


def test_foreign_active_merge_is_never_overwritten(execution_case: ExecutionCase) -> None:
    c = execution_case
    c.interrupt = True
    with pytest.raises(KeyboardInterrupt):
        c.resume()
    c.restart()
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None and isinstance(c.ports.files, FakeSlotFiles)
    c.ports.files.contents[work.gitdir / "MERGE_HEAD"] = ("f" * 40 + "\n").encode()
    before = c.slot.read_file("README")
    result = c.resume()
    assert isinstance(result, Terminal) and result.reason is Reason.MOVED
    assert c.calls == 1 and c.slot.merging() and c.slot.read_file("README") == before


def test_completed_result_does_not_accept_later_slot_edits(execution_case: ExecutionCase) -> None:
    c = execution_case
    assert isinstance(c.resume(), Completed)
    c.slot.write_file("foreign", "retain this edit")
    c.restart()
    assert isinstance(c.resume(), Unavailable) and c.calls == 1 and c.slot.read_file("foreign") == "retain this edit"
