"""Conflict execution obeys exact durable ownership, setup process fences and slot custody."""

from collections.abc import Generator
from dataclasses import replace
from pathlib import Path
from typing import Literal

import land_conflict_bench
import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome
from doubles import FakeSlotFiles
from git_porcelain.testing import FakeRepo, FakeWorktree
from land_conflict_bench import ExecutionCase
from merge_bench import head
from stream_proc import OwnedProcess

from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_types import AttemptKey
from taskloop.command_conclusion import CommandConclusion
from taskloop.merge.models import Completed, Unavailable
from taskloop.setup_store import SetupStore
from taskloop.slot_lock import landing


@pytest.fixture
def repo(tmp_path: Path) -> FakeRepo:
    return land_conflict_bench.execution_repo(tmp_path)


@pytest.fixture
def execution_case(on_slot: Path, repo: FakeRepo, slot: FakeWorktree, tmp_path: Path) -> Generator[ExecutionCase]:
    yield from land_conflict_bench.execution_case(on_slot, repo, slot, tmp_path)


def test_execution_prepares_the_reserved_base_and_keeps_checked_refs(execution_case: ExecutionCase) -> None:
    c = execution_case
    branches = dict(c.ports.repo.branches("task/"))
    result = c.resume()
    assert isinstance(result, Completed) and result.source == c.record.request.checked and result.target == c.record.request.target
    assert c.slot.branch() is None and head(c.slot) == result.commit and not c.slot.merging()
    assert dict(c.ports.repo.branches("task/")) == branches and c.calls == 1
    assert c.environment.probes and c.environment.process.calls[0].cwd == c.record.slot_path
    assert c.con.execute("SELECT attempt_id,generation FROM reservation").fetchone() == (
        c.record.key.attempt_id, c.record.key.reservation_generation)
    assert c.con.execute("SELECT count(*) FROM attempt").fetchone() == (1,)
    assert SetupStore(lambda: c.con).drain_processes()[0].subject == c.record.key.attempt_id


@pytest.mark.parametrize("changed", ["token", "key_generation", "reservation", "slot_generation", "path", "repo"])
def test_stale_ownership_prevents_all_effects(execution_case: ExecutionCase, changed: str) -> None:
    c, key = execution_case, execution_case.record.key
    if changed == "token":
        key = AttemptKey(key.attempt_id, "foreign", key.reservation_generation)
    elif changed == "key_generation":
        key = AttemptKey(key.attempt_id, key.dispatch_token, key.reservation_generation + 1)
    elif changed == "reservation":
        c.con.execute("DELETE FROM reservation")
    elif changed == "slot_generation":
        c.con.execute("UPDATE slot SET generation=generation+1 WHERE name='s1'")
    elif changed == "path":
        c.con.execute("UPDATE slot SET path='/other/s1' WHERE name='s1'")
    else:
        assert isinstance(c.ports.files, FakeSlotFiles)
        c.ports.files.contents[c.slot.path / ".git"] = b"gitdir: /foreign/worktrees/s1\n"
    before = head(c.slot)
    result = c.resume(key)
    assert isinstance(result, Unavailable) and result.explanation
    assert head(c.slot) == before and c.calls == 0 and not c.environment.events
    assert c.ports.merges.get(c.record.key.attempt_id) is None


def test_busy_slot_has_no_setup_or_merge_effect(execution_case: ExecutionCase) -> None:
    c = execution_case
    with landing(c.record.slot_path, "other"):
        result = c.resume()
    assert isinstance(result, Unavailable) and c.calls == 0 and not c.environment.events
    assert c.ports.merges.get(c.record.key.attempt_id) is None


@pytest.mark.parametrize("seen", ["alive", "unknown"])
def test_previous_setup_blocks_parking_and_remains_visible_to_drain(
    execution_case: ExecutionCase, seen: Literal["alive", "unknown"],
) -> None:
    c = execution_case
    store = SetupStore(lambda: c.con)
    store.start(c.record.key, 1, c.record.request.target, "d" * 64, 10)
    worker = OwnedProcess(501, 501, "start", "boot")
    store.registered(c.record.key, 1, 0, worker)
    c.environment.seen[501] = seen
    result = c.resume()
    assert isinstance(result, Unavailable) and head(c.slot) == c.record.base and c.calls == 0
    assert store.drain_processes()[0].identity.pid == worker.pid
    latest = store.latest(c.record.key)
    assert latest is not None and latest.unsettled == worker


def test_setup_registration_rechecks_slot_identity(execution_case: ExecutionCase) -> None:
    c = execution_case
    store = SetupStore(lambda: c.con)
    store.start(c.record.key, 1, c.record.request.target, "d" * 64, 10)
    c.con.execute("UPDATE slot SET path='/other/s1' WHERE name='s1'")
    with pytest.raises(StoreRefused, match="stale_reservation"):
        store.registered(c.record.key, 1, 0, OwnedProcess(501, 501, "start", "boot"))
    with pytest.raises(StoreRefused, match="stale_reservation"):
        store.conclude(c.record.key, 1, CommandConclusion.PASSED, 0, 11)


def test_setup_fence_rechecks_ownership_after_probe(execution_case: ExecutionCase) -> None:
    c = execution_case

    def revoke(*_args: object) -> bool:
        c.con.execute("DELETE FROM reservation")
        return True

    preparation = c.environment.preparation()
    preparation.ports = replace(preparation.ports, probe=revoke)
    c.ports = replace(c.ports, environment=preparation)
    result = c.resume()
    assert isinstance(result, Unavailable) and c.calls == 0 and not c.environment.process.calls


@pytest.mark.parametrize("field", ["dispatch_token", "generation", "source", "target", "input_path", "branch"])
def test_retained_merge_cannot_replace_admission_facts(execution_case: ExecutionCase, field: str) -> None:
    c = execution_case
    c.interrupt = True
    with pytest.raises(KeyboardInterrupt):
        c.resume()
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None
    replacement = 99 if field == "generation" else "f" * 40
    c.ports.merges.put(work, work.model_copy(update={field: replacement}))
    c.restart()
    before = c.slot.read_file("README")
    assert isinstance(c.resume(), Unavailable) and c.calls == 1
    assert c.slot.read_file("README") == before


def test_resolution_registration_is_fenced_before_target_execution(execution_case: ExecutionCase) -> None:
    c = execution_case

    def revoked(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        c.con.execute("DELETE FROM reservation")
        return c.run(harness, spec, timeout, hooks)

    c.ports = replace(c.ports, run=revoked)
    before = dict(c.ports.repo.branches())
    assert isinstance(c.resume(), Unavailable)
    work = c.ports.merges.get(c.record.key.attempt_id)
    assert work is not None and len(work.executions) == 1 and work.executions[0].worker is None
    readme = c.slot.read_file("README")
    assert readme is not None and "<<<<<<<" in readme and dict(c.ports.repo.branches()) == before
