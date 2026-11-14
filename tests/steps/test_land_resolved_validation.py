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
from taskloop.merge.models import Completed
from taskloop.operations import Failed


@pytest.fixture
def b(tmp_path: Path) -> Iterator[LandBench]:
    world = bench(tmp_path, {"README": "the task\n"})
    yield world
    world.con.close()


def completed(b: LandBench, *, edit: Callable[[FakeWorktree], None] | None = None,
              target: dict[str, str | None] | None = None) -> tuple[LandPorts, ExecutionCase, Completed]:
    b.advance({"README": "current main\n"} | (target or {}))
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
    assert saved is not None and saved.commit == result.commit
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
    ports, case, result = completed(b, target={".task-loop.json": json.dumps(profile)})
    b.environment.profiles.data = json.dumps(profile).encode()
    found = land(ports, request(b))
    assert isinstance(found, Landed) and found.row.origin == result.target
    assert [name for name, _digest in found.row.required] == ["test"]
    assert b.execs() == RUN
    preserved(b, ports, case, result)


def test_equal_checked_tree_still_runs_validation(b: LandBench) -> None:
    ports, case, result = completed(b, edit=lambda slot: slot.write_file("README", "the task\n"))
    found = land(ports, request(b))
    assert isinstance(found, Landed) and found.row.tree_same and found.row.validation == "passed"
    assert b.execs() == RUN and found.row.slot is not None
    preserved(b, ports, case, result)


@pytest.mark.parametrize("failure", ["minutes", "target", "gate", "checks"])
def test_resolution_is_preserved_when_fresh_validation_cannot_deliver(b: LandBench, failure: str) -> None:
    ports, case, result = completed(b)
    if failure == "target":
        b.advance({"other": "target moved\n"})
    if failure == "checks":
        b.environment.process.script = [Command(), Command(rc=1)]
    target = b.origin_main()
    found = land(ports, replace(request(b, None if failure == "minutes" else 5), accept=failure != "gate"))
    reasons = {"minutes": "minutes", "target": "conflict", "gate": "gate_changed", "checks": "checks_failed"}
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
