"""A merge's separate, bounded executions survive restarts without relaunching a live process."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from doubles import FakeSlotFiles, PinnedViews
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree
from merge_bench import Bench, MergeRepo, bench

from taskloop.agents.launch import AgentLaunch
from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import EvidenceFiles
from taskloop.ids import NativeIds
from taskloop.merge.models import Completed, InProgress, Phase, Reason, Terminal, Work
from taskloop.merge.resolve import Resolution
from taskloop.merge.start import Merge
from taskloop.merge.store import MergeStore

WORKER = Worker(pid=42, pgid=42, start="start", boot="boot")


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
    case.work = case.store.put(case.work, case.work.model_copy(update={
        "input_digest": hashlib.sha256(b"Plan the actual task").hexdigest()}))
    return case


class Agent:
    def __init__(self, case: Bench, disposition: str = "resolved") -> None:
        self.case, self.disposition, self.calls = case, disposition, 0
        self.gone, self.interrupt = True, False

    def run(self, harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        self.calls += 1
        assert hooks is not None and hooks.started is not None
        hooks.started(WORKER)
        if self.interrupt:
            raise KeyboardInterrupt
        if self.disposition == "resolved":
            self.case.slot.write_file("README", "the task\ncurrent main\n")
        text = json.dumps({"disposition": self.disposition, "paths": ["README"] if self.disposition == "resolved" else [],
                           "explanation": "Retain both changes." if self.disposition == "resolved" else "A decision is needed."})
        result = RunOutcome(rc=0, worker=WORKER, summary=Summary(text=text, rc=0, stands=True, res={"ref": "native-session"}))
        return FakeRun(result, refs=("native-session",))(harness, spec, timeout, hooks)

    def operation(self, root: Path) -> Merge:
        operation = self.case.operation()
        operation.resolve = Resolution(self.case.store, AgentLaunch(lambda _h: ("/bin/codex", {}), ids=NativeIds()), EvidenceFiles(root),
                                       self.run, lambda _worker: self.gone, lambda: 10, lambda: None)
        return operation


def test_resolution_records_its_own_session_evidence_and_input(conflict: Bench, tmp_path: Path) -> None:
    agent = Agent(conflict)
    result = agent.operation(tmp_path).resume(conflict.work)
    assert isinstance(result, Completed) and agent.calls == 1
    stored = conflict.store.get("attempt")
    assert stored is not None and len(stored.executions) == 1
    execution = stored.executions[0]
    assert execution.session == "native-session" and execution.worker is not None and execution.ended
    assert len(execution.evidence) == 4 and all((tmp_path / ref.path).is_file() for ref in execution.evidence)
    assert conflict.store.active_processes() == ()


def test_restart_observes_a_surviving_execution_without_spending_another_execution(conflict: Bench, tmp_path: Path) -> None:
    agent = Agent(conflict)
    agent.gone, agent.interrupt = False, True
    with pytest.raises(KeyboardInterrupt):
        agent.operation(tmp_path).resume(conflict.work)
    stored = conflict.store.get("attempt")
    assert stored is not None and stored.phase is Phase.RESOLVE
    assert len(conflict.store.active_processes()) == 1
    pending = agent.operation(tmp_path).resume(stored)
    assert isinstance(pending, InProgress) and agent.calls == 1
    latest = conflict.store.get("attempt")
    assert latest is not None and len(latest.executions) == 1
    agent.gone, agent.interrupt = True, False
    agent.operation(tmp_path).resume(latest)  # records interruption and requests the next bounded execution
    latest = conflict.store.get("attempt")
    assert latest is not None
    assert isinstance(agent.operation(tmp_path).resume(latest), Completed) and agent.calls == 2


def test_three_executions_exhaust_the_same_durable_operation_across_restarts(conflict: Bench, tmp_path: Path) -> None:
    agent = Agent(conflict, "incomplete")
    result = agent.operation(tmp_path).resume(conflict.work)
    for _ in range(2):
        stored = conflict.store.get("attempt")
        assert stored is not None
        result = agent.operation(tmp_path).resume(stored)
    assert isinstance(result, Terminal) and result.reason is Reason.EXHAUSTED and agent.calls == 3
    stored = conflict.store.get("attempt")
    assert stored is not None
    assert isinstance(agent.operation(tmp_path).resume(stored), Terminal) and agent.calls == 3
    assert conflict.slot.merging() and conflict.slot.read_file("docs/design/tl-1/plan.md") is not None


def test_needs_owner_is_terminal_without_running_the_ordinary_step(conflict: Bench, tmp_path: Path) -> None:
    agent = Agent(conflict, "needs_owner")
    result = agent.operation(tmp_path).resume(conflict.work)
    assert isinstance(result, Terminal) and result.reason is Reason.OWNER and result.explanation == "A decision is needed."
    assert agent.calls == 1 and conflict.slot.merging()


def test_crash_after_evidence_capture_adopts_the_same_execution(
    conflict: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(conflict)
    capture = EvidenceFiles.capture

    def interrupted(self: EvidenceFiles, key: AttemptKey, raw: RunOutcome) -> None:
        capture(self, key, raw)
        raise KeyboardInterrupt

    monkeypatch.setattr(EvidenceFiles, "capture", interrupted)
    with pytest.raises(KeyboardInterrupt):
        agent.operation(tmp_path).resume(conflict.work)
    work = conflict.store.get("attempt")
    assert work is not None and work.executions[-1].capturing
    monkeypatch.setattr(EvidenceFiles, "capture", capture)
    assert isinstance(agent.operation(tmp_path).resume(work), Completed) and agent.calls == 1


def test_third_execution_intent_is_retried_when_registration_never_committed(
    conflict: Bench, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(conflict, "incomplete")
    agent.operation(tmp_path).resume(conflict.work)
    work = conflict.store.get("attempt")
    assert work is not None
    agent.operation(tmp_path).resume(work)
    work = conflict.store.get("attempt")
    assert work is not None and len(work.executions) == 2
    put = MergeStore.put

    def interrupted(self: MergeStore, previous: Work, updated: Work) -> Work:
        result = put(self, previous, updated)
        if len(updated.executions) == 3 and updated.executions[-1].worker is None:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(MergeStore, "put", interrupted)
    with pytest.raises(KeyboardInterrupt):
        agent.operation(tmp_path).resume(work)
    assert agent.calls == 2
    work = conflict.store.get("attempt")
    assert work is not None and len(work.executions) == 3 and work.executions[-1].worker is None
    monkeypatch.setattr(MergeStore, "put", put)
    result = agent.operation(tmp_path).resume(work)
    assert isinstance(result, Terminal) and result.reason is Reason.EXHAUSTED and agent.calls == 3
