"""Resolved content keeps its original attribution and receives current-target validation before delivery."""

import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Never

import pytest
from doubles import CHECKS, Command
from git_porcelain import Transient
from git_porcelain.testing import FakeWorktree
from land_bench import PROFILE, RUN, LandBench, bench, executing
from land_conflict_bench import ExecutionCase

from taskloop.attempt_types import AttemptKey
from taskloop.land import Landed, LandRequest, land
from taskloop.land_check import LandPorts
from taskloop.land_conflict.store import ConflictStore
from taskloop.land_store import Close, LandStore
from taskloop.merge.models import Completed
from taskloop.operations import Failed
from taskloop.tracker_client import CloseAnswer


@pytest.fixture
def b(tmp_path: Path) -> Iterator[LandBench]:
    world = bench(tmp_path, {"README": "the task\n"})
    yield world
    world.con.close()


def completed(b: LandBench, *, edit: Callable[[FakeWorktree], None] | None = None) -> tuple[LandPorts, ExecutionCase, Completed]:
    b.advance({"README": "current main\n"})
    b.land()  # admit without executing, then finish using the actual retained execution/release protocol
    ports, cases = executing(b, edit=edit)
    checks = ports.work.store.row(CHECKS)
    assert checks is not None
    result = ports.conflicts.resume(b.repo, AttemptKey("implement", "implement-token", 1), checks)
    assert isinstance(result, Completed) and len(cases) == 1 and cases[0].calls == 1
    b.environment.events.clear()
    return ports, cases[0], result


def request(b: LandBench, minutes: int | None = 5) -> LandRequest:
    return LandRequest("tasks", "tl-1", b.repo.path, minutes, accept=True)


def preserved(b: LandBench, ports: LandPorts, case: ExecutionCase, result: Completed) -> None:
    saved = ports.conflicts.store.completed(case.record.key)
    assert saved is not None and (saved.source, saved.target, saved.commit) == (result.source, result.target, result.commit)
    assert saved.accepted and saved.release is not None and saved.release.result == result
    assert b.files_of(saved.ref)["README"] == b.files_of(result.commit)["README"]
    assert dict(b.repo.branches("task/"))["task/tl-1"] == b.x
    assert b.con.execute("SELECT end_commit FROM attempt").fetchall() == [(b.x,)]
    checks = ports.work.store.row(CHECKS)
    assert checks is not None and checks.commit == b.x
    assert case.calls == 1


def interrupt() -> Never:
    raise KeyboardInterrupt


def test_newly_completed_resolution_validates_and_delivers_in_the_same_land(b: LandBench) -> None:
    target = b.advance({"README": "current main\n"})
    ports, cases = executing(b)
    found = land(ports, request(b))
    assert isinstance(found, Landed) and found.how == "pushed" and found.row.validation == "passed"
    assert found.row.origin == target and found.row.checked == b.x and found.row.checks == CHECKS.attempt_id
    assert b.files_of(found.row.commit)["README"] == "X\ncurrent main\n"
    assert b.origin_main() == found.row.commit and b.status == "closed" and b.repo.pushes == 1
    assert b.reservations() == [] and len(cases) == 1 and cases[0].calls == 1
    assert "Checked: checks passed at " + b.x in b.repo._state.store.commits[found.row.commit].message


def test_released_completion_survives_restart_without_execution_or_credentials(b: LandBench) -> None:
    ports, case, result = completed(b)
    case.restart()
    b.con = case.con
    ports = b.ports()

    def forbidden(*_args: object) -> Never:
        pytest.fail("completed resolution was executed again")

    ports = replace(ports, conflicts=replace(ports.conflicts, execution=forbidden, admission=forbidden))
    found = land(ports, request(b))
    assert isinstance(found, Landed) and found.row.validation == "passed" and b.execs() == RUN
    preserved(b, ports, case, result)


def test_slot_reuse_does_not_reexecute_resolution_or_touch_new_work(b: LandBench) -> None:
    ports, case, result = completed(b)
    record = case.record
    b.con.execute("UPDATE slot SET generation=generation+1 WHERE name=?", (record.slot,))
    b.con.execute("INSERT INTO reservation(repo_id,slot,attempt_id,generation) VALUES (?,?,?,?)",
                  (record.request.repo_id, record.slot, "new-owner", record.key.reservation_generation + 1))
    b.slot.write_file("new-owner", "keep new work\n")
    found = land(ports, request(b))
    assert isinstance(found, Failed) and found.reason == "no_free_slot"
    assert b.rows() == () and b.repo.pushes == 0 and b.execs() == []
    assert b.slot.read_file("new-owner") == "keep new work\n"
    assert b.reservations() == [(record.slot, "new-owner")]
    preserved(b, ports, case, result)


def test_validation_uses_fresh_target_required_checks(b: LandBench) -> None:
    profile = PROFILE | {"required": ["test"]}
    ports, case, result = completed(b)
    target = b.advance({".task-loop.json": json.dumps(profile)})
    b.environment.profiles.data = json.dumps(profile).encode()
    found = land(ports, request(b))
    assert isinstance(found, Landed) and found.row.origin == target and target != result.target
    assert [name for name, _digest in found.row.required] == ["test"]
    assert b.execs() == RUN
    preserved(b, ports, case, result)


def test_equal_checked_tree_still_runs_validation(b: LandBench) -> None:
    ports, case, result = completed(b, edit=lambda slot: slot.write_file("README", "the task\n"))
    found = land(ports, request(b))
    assert isinstance(found, Landed) and found.row.tree_same and found.row.validation == "passed"
    assert b.execs() == RUN and found.row.slot is not None
    preserved(b, ports, case, result)


@pytest.mark.parametrize("failure", ["minutes", "gate", "checks"])
def test_resolution_is_preserved_when_fresh_validation_cannot_deliver(b: LandBench, failure: str) -> None:
    ports, case, result = completed(b)
    if failure == "checks":
        b.environment.process.script = [Command(), Command(rc=1)]
    target = b.origin_main()
    found = land(ports, replace(request(b, None if failure == "minutes" else 5), accept=failure != "gate"))
    reasons = {"minutes": "minutes", "gate": "gate_changed", "checks": "checks_failed"}
    assert isinstance(found, Failed) and found.reason == reasons[failure]
    assert b.origin_main() == target and b.repo.pushes == 0 and b.tracker == []
    if failure != "checks":
        assert b.rows() == () and b.execs() == []
    else:
        assert b.rows()[0].validation == "failed" and b.reservations() == []
    preserved(b, ports, case, result)


@pytest.mark.parametrize("evidence", ["ref", "object", "release", "mismatch"])
def test_incomplete_or_missing_completion_evidence_never_promotes(
    b: LandBench, monkeypatch: pytest.MonkeyPatch, evidence: str,
) -> None:
    ports, case, result = completed(b)
    saved = ports.conflicts.store.completed(case.record.key)
    assert saved is not None
    if evidence == "ref":
        b.repo.update_ref(saved.ref, b.x, expected=result.commit)
    elif evidence == "object":
        b.repo.prune(result.commit)
    elif evidence == "release":
        monkeypatch.setattr(ConflictStore, "completed", lambda _self, _key: None)
        ports = replace(ports, conflicts=replace(ports.conflicts, execution=lambda _repo, _record: result))
    else:
        forged = result.model_copy(update={"source": b.base})
        assert saved.release is not None
        mismatched = saved.model_copy(update={"release": saved.release.model_copy(update={"result": forged})})
        monkeypatch.setattr(ConflictStore, "completed", lambda _self, _key: mismatched)
    found = land(ports, request(b))
    assert isinstance(found, Failed) and found.detail
    assert b.rows() == () and b.repo.pushes == 0 and b.tracker == [] and b.execs() == [] and case.calls == 1


def test_interruption_before_insertion_reuses_completion(b: LandBench) -> None:
    ports, case, result = completed(b)
    b.racing = interrupt
    with pytest.raises(KeyboardInterrupt):
        land(ports, request(b))
    assert b.rows() == () and b.reservations() == []
    found = land(ports, request(b))
    assert isinstance(found, Landed) and found.row.validation == "passed" and len(b.rows()) == 1
    preserved(b, ports, case, result)


def test_pending_candidate_resumes_with_liveness_and_renewed_deadline(b: LandBench) -> None:
    ports, case, result = completed(b)
    b.environment.process.script = [Command(), Command(), Command(effect=interrupt)]
    with pytest.raises(KeyboardInterrupt):
        land(ports, request(b))
    [row] = b.rows()
    assert row.pending and row.commit != b.x
    case.restart()
    b.con = case.con
    assert isinstance(land(ports, request(b, None)), Failed)
    pid = b.con.execute("SELECT pid FROM check_result WHERE conclusion IS NULL").fetchone()[0]
    b.environment.seen[pid] = "alive"
    b.me = (5555, "next-start", "boot")
    waiting = land(b.ports(), request(b))
    assert isinstance(waiting, Failed) and waiting.reason == "checks:running"
    b.now, b.environment.seen[pid] = 1000.0, "gone"
    b.environment.process.script = []
    found = land(b.ports(), request(b))
    assert isinstance(found, Landed) and found.row.key == row.key and found.row.commit == row.commit
    assert found.row.deadline == 1300.0 and found.row.validation == "passed" and len(b.rows()) == 1
    assert b.conflict_runs == [case.record]  # only the fixture admission used the fake conflict executor
    preserved(b, ports, case, result)


def test_passed_candidate_resumes_delivery_before_conflict_lookup(b: LandBench, monkeypatch: pytest.MonkeyPatch) -> None:
    ports, case, result = completed(b)
    b.repo.answer = Transient("connection reset")
    stopped = land(ports, request(b))
    assert isinstance(stopped, Failed) and stopped.reason == "remote"
    [row] = b.rows()
    assert row.pushable and row.delivery is None and b.execs() == RUN

    def forbidden(*_args: object) -> Never:
        pytest.fail("validated candidate revisited conflict work")

    monkeypatch.setattr(ConflictStore, "find", forbidden)
    found = land(b.ports(), request(b, None))
    assert isinstance(found, Landed) and found.row.key == row.key and b.repo.pushes == 2 and b.execs() == RUN
    preserved(b, ports, case, result)


@pytest.mark.parametrize("movement", ["construction", "validation", "push"])
def test_moved_target_rebuilds_from_resolved_content_and_validates(b: LandBench, movement: str) -> None:
    ports, case, result = completed(b)

    def move() -> str:
        return b.advance({"OTHER": "another task\n"})

    if movement == "construction":
        move()
    elif movement == "validation":
        b.environment.process.script = [Command(), Command(effect=move)]
    else:
        b.repo.after_ls = [None, move]
    found = land(ports, request(b))
    if movement != "construction":
        assert isinstance(found, Failed) and found.reason == "target_moved"
        [first] = b.rows()
        assert first.superseded == "moved" and first.delivery is None and first.validation == "passed"
        assert b.tracker == [] and b.repo.pushes == (1 if movement == "push" else 0)
        preserved(b, ports, case, result)
        found = land(b.ports(), request(b))
    assert isinstance(found, Landed) and found.row.validation == "passed"
    assert found.row.origin != result.target and b.origin_main() == found.row.commit
    files = b.files_of(found.row.commit)
    assert files["README"] == "X\ncurrent main\n" and files["OTHER"] == "another task\n"
    assert b.execs() == RUN * (1 if movement == "construction" else 2)
    assert all(row.checked == b.x for row in b.rows())
    assert b.repo.pushes == (2 if movement == "push" else 1) and b.status == "closed"
    preserved(b, ports, case, result)


def test_pushable_resolution_rebuilds_once_during_delivery_to_a_moved_target(b: LandBench) -> None:
    ports, case, result = completed(b)
    b.repo.answer = Transient("connection reset")
    stopped = land(ports, request(b))
    assert isinstance(stopped, Failed) and stopped.reason == "remote"
    [first] = b.rows()
    target = b.advance({"OTHER": "new target content\n"})
    found = land(b.ports(), request(b))
    assert isinstance(found, Landed) and found.row.number == 2 and found.row.origin == target
    assert found.row.checked == b.x and found.row.validation == "passed" and b.origin_main() == found.row.commit
    files = b.files_of(found.row.commit)
    assert files["README"] == "X\ncurrent main\n" and files["OTHER"] == "new target content\n"
    old, new = b.rows()
    assert old.key == first.key and old.superseded == "moved" and old.delivery is None
    assert new.delivery == "pushed" and b.execs() == RUN * 2 and b.repo.pushes == 2
    preserved(b, ports, case, result)


@pytest.mark.parametrize("validated", [False, True])
def test_renewed_conflict_preserves_resolution_without_another_agent(b: LandBench, validated: bool) -> None:
    ports, case, result = completed(b)
    if validated:
        b.repo.answer = Transient("connection reset")
        stopped = land(ports, request(b))
        assert isinstance(stopped, Failed) and stopped.reason == "remote"
    target = b.advance({"README": "incompatible later change\n"})
    pushes, commands = b.repo.pushes, b.execs()
    found = land(b.ports(), request(b))
    assert isinstance(found, Failed) and found.reason == "conflict"
    assert b.origin_main() == target and b.repo.pushes == pushes and b.tracker == [] and b.execs() == commands
    assert all(row.delivery is None and row.superseded == "moved" for row in b.rows())
    assert b.reservations() == []
    preserved(b, ports, case, result)


@pytest.mark.parametrize("containing_tip", [False, True])
def test_interrupted_push_is_adopted_after_restart_without_repeating_work(
    b: LandBench, monkeypatch: pytest.MonkeyPatch, containing_tip: bool,
) -> None:
    ports, case, result = completed(b)

    def lose_delivery(_self: LandStore, _key: AttemptKey, _head: str, _now: float) -> Never:
        assert not b.con.in_transaction and b.repo.pushes == 1
        interrupt()

    with monkeypatch.context() as patch:
        patch.setattr(LandStore, "record_delivery", lose_delivery)
        with pytest.raises(KeyboardInterrupt):
            land(ports, request(b))
    [row] = b.rows()
    assert row.pushable and row.delivery is None and b.origin_main() == row.commit and b.tracker == []
    head = b.advance({"LATER": "on top of resolution\n"}) if containing_tip else row.commit
    case.restart()
    b.con = case.con

    def forbidden(*_args: object) -> Never:
        pytest.fail("delivery adoption revisited conflict work")

    monkeypatch.setattr(ConflictStore, "find", forbidden)
    b.remote.offline = True
    unavailable = land(b.ports(), request(b, None))
    assert isinstance(unavailable, Failed) and b.rows()[0].delivery is None and b.tracker == []
    b.remote.offline = False
    found = land(b.ports(), request(b, None))
    assert isinstance(found, Landed) and found.how == "already_pushed" and found.row.key == row.key
    assert found.row.remote_head == head and found.row.close == "closed"
    assert b.repo.pushes == 1 and b.execs() == RUN and b.tracker == [("tl-1", head)]
    assert b.files_of(found.row.commit)["README"] == "X\ncurrent main\n"
    preserved(b, ports, case, result)
    b.remote.offline = True
    again = land(b.ports(), request(b, None))
    assert isinstance(again, Landed) and again.how == "already_landed" and again.row == found.row
    assert b.repo.pushes == 1 and b.execs() == RUN and b.tracker == [("tl-1", head)]


@pytest.mark.parametrize("performed", [False, True])
def test_interrupted_close_is_finished_or_adopted_after_restart(
    b: LandBench, monkeypatch: pytest.MonkeyPatch, performed: bool,
) -> None:
    ports, case, result = completed(b)

    def lose_close(_self: LandStore, _key: AttemptKey, _close: Close, _now: float) -> Never:
        assert not b.con.in_transaction and b.status == "closed"
        interrupt()

    with monkeypatch.context() as patch:
        if performed:
            patch.setattr(LandStore, "record_close", lose_close)
        else:
            b.on_close = interrupt
        with pytest.raises(KeyboardInterrupt):
            land(ports, request(b))
    [row] = b.rows()
    assert row.delivery == "pushed" and row.close is None and b.origin_main() == row.commit
    original_reason = b.reason
    assert b.status == ("closed" if performed else "in_progress")
    case.restart()
    b.con = case.con
    b.on_close = lambda: None
    b.remote.offline = True
    ports = b.ports()
    # Use the adapter's observation contract: an already closed task causes no close effect.
    close = ports.close
    ports = replace(ports, close=lambda root, task, reason: CloseAnswer("already_closed")
                    if b.status == "closed" else close(root, task, reason))
    found = land(ports, request(b, None))
    assert isinstance(found, Landed) and found.how == "delivered" and found.row.key == row.key
    assert found.row.close == ("already_closed" if performed else "closed")
    assert b.repo.pushes == 1 and b.execs() == RUN and b.tracker == [("tl-1", row.commit)]
    assert b.reason == (original_reason if performed else f"Landed {row.commit} on main (task/tl-1 at {b.x})")
    preserved(b, ports, case, result)

    def forbidden(*_args: object) -> Never:
        pytest.fail("final result repeated tracker observation or close")

    ports = replace(ports, close=forbidden)
    again = land(ports, request(b, None))
    assert isinstance(again, Landed) and again.how == "already_landed" and again.row == found.row
    assert b.repo.pushes == 1 and b.execs() == RUN and b.tracker == [("tl-1", row.commit)]
