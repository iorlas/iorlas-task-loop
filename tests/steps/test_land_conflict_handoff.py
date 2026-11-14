"""Ordinary land retains conflict execution and consumes only durably accepted completion."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from git_porcelain import Repo
from land_bench import LandBench, bench, executing
from land_conflict_bench import ExecutionCase
from sqlite_store import Store

from taskloop.attempt_types import AttemptKey
from taskloop.dash_land import build_land
from taskloop.dash_model import LandDetail
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.land import LandRequest, land
from taskloop.land_conflict.admit import Ports, admit
from taskloop.land_conflict.composition import conflict_handoff
from taskloop.land_conflict.execute import Ports as ExecutionPorts
from taskloop.land_conflict.execute import execute
from taskloop.land_conflict.handoff import request_for
from taskloop.land_summary import LandSummary
from taskloop.merge.models import Completed, Phase, Result
from taskloop.operations import Failed


@pytest.fixture
def b(tmp_path: Path) -> Iterator[LandBench]:
    world = bench(tmp_path, {"README": "the task\n"})
    yield world
    world.con.close()


def unchanged_input(b: LandBench, target: str) -> None:
    assert b.rows() == () and b.repo.pushes == 0 and b.tracker == [] and b.status == "in_progress"
    assert b.origin_main() == target and not {"exec just check", "exec just test"}.intersection(b.execs())
    assert dict(b.repo.branches("task/")) == {"task/tl-1": b.x}
    assert b.remote.branches()["task/tl-1"] == b.x
    assert b.con.execute("SELECT end_commit FROM attempt").fetchall() == [(b.x,)]
    assert b.con.execute("SELECT target_commit FROM checks_attempt").fetchall() == [(b.base,)]


def test_new_conflict_needs_minutes_before_admission_and_other_modes_never_execute(b: LandBench) -> None:
    target = b.advance({"README": "current main\n"})
    found = b.land(minutes=None)
    assert isinstance(found, Failed) and found.word == "refused:minutes"
    assert b.reservations() == [] and b.conflict_runs == []
    b.land("summary")
    b.land("withdraw")
    b.land(no_change=True)
    assert b.reservations() == [] and b.conflict_runs == []
    unchanged_input(b, target)


def test_admission_retains_exact_checked_inputs_target_and_deadline(b: LandBench) -> None:
    target = b.advance({"README": "current main\n"})
    found = b.land(minutes=3)
    assert isinstance(found, Failed) and found.word == "refused:conflict" and found.detail
    [record] = b.conflict_runs
    assert record.request.target == target and record.request.deadline == b.now + 180
    assert record.request.source == AttemptKey("implement", "implement-token", 1)
    assert record.request.checked == b.x and record.inputs.input_ref.digest
    assert b.reservations() == [("s1", record.key.attempt_id)]
    unchanged_input(b, target)


def test_unavailable_admission_stays_retryable_without_execution(b: LandBench) -> None:
    target = b.advance({"README": "current main\n"})
    ports = b.ports()

    def unavailable(repo: Repo) -> Ports:
        return replace(ports.conflicts.admission(repo), probe=lambda _path: False)

    denied = replace(ports, conflicts=replace(ports.conflicts, admission=unavailable))
    found = land(denied, LandRequest("tasks", "tl-1", b.repo.path, 5))
    assert isinstance(found, Failed) and found.word == "unavailable:no_slot" and found.detail
    assert b.conflict_runs == [] and b.reservations() == []
    assert isinstance(b.land(), Failed) and len(b.conflict_runs) == 1
    unchanged_input(b, target)


def test_restart_and_now_clean_main_resume_original_work_without_minutes_or_free_slot(b: LandBench) -> None:
    b.advance({"README": "current main\n"})
    b.land(minutes=3)
    [record] = b.conflict_runs
    b.con.close()
    con = Store(SCHEMA).open_rw(b.root / "factory.db")
    assert con is not None
    b.con, b.environment.con = con, con
    b.now += 100
    target = b.advance({"README": "the task\n"})
    found = b.land(minutes=None)
    assert isinstance(found, Failed) and found.word == "refused:conflict"
    assert b.conflict_runs == [record, record] and b.reservations() == [("s1", record.key.attempt_id)]
    unchanged_input(b, target)


def test_a_racing_admission_is_resumed_with_its_own_deadline(b: LandBench) -> None:
    target = b.advance({"README": "current main\n"})
    ports = b.ports()
    original_admission = ports.conflicts.admission

    def admission(repo: Repo) -> Ports:
        dependencies = original_admission(repo)
        checks = ports.work.store.row(AttemptKey("checks", "checks-token", 1))
        assert checks is not None
        winner = admit(dependencies, request_for(AttemptKey("implement", "implement-token", 1), checks, target, 111.0))
        assert winner.record is not None
        return dependencies

    ports = replace(ports, conflicts=replace(ports.conflicts, admission=admission))
    found = land(ports, LandRequest("tasks", "tl-1", b.repo.path, 5))
    assert isinstance(found, Failed) and found.word == "refused:conflict"
    [record] = b.conflict_runs
    assert record.request.deadline == 111.0 and b.reservations() == [("s1", record.key.attempt_id)]


def test_completed_resolution_and_repeated_reads_preserve_content_without_minutes(b: LandBench) -> None:
    target = b.advance({"README": "current main\n"})
    ports, cases = executing(b)
    request = LandRequest("tasks", "tl-1", b.repo.path, 5, accept=True)
    b.land()  # admit the conflict before completing it through the real execution adapter
    checks = ports.work.store.row(AttemptKey("checks", "checks-token", 1))
    assert checks is not None
    first = ports.conflicts.resume(b.repo, AttemptKey("implement", "implement-token", 1), checks)
    assert isinstance(first, Completed)
    [case] = cases
    work = case.ports.merges.get(case.record.key.attempt_id)
    saved = ports.conflicts.store.completed(case.record.key)
    assert work is not None and work.phase is Phase.COMPLETE and saved is not None and saved.accepted
    assert case.record.request.target == target and case.record.request.deadline == b.now + 300
    assert case.record.request.checked == b.x
    reservations = b.reservations()
    assert reservations == []
    before = list(b.environment.events)
    for clean in (False, True):
        if clean:
            b.now += 100
            target = b.advance({"README": "the task\n"})
        for _ in range(2):
            summary = land(ports, replace(request, minutes=None, mode="summary"))
            assert isinstance(summary, LandSummary)
            assert summary.origin == target and summary.x == b.x
            assert (summary.state, summary.conflicts) == (("no_change", ()) if clean else ("conflict", ("README",)))
            dashboard = build_land(ports, "tasks", "tl-1", b.repo.path)
            assert isinstance(dashboard, LandDetail)
            action = "main already contains" if clean else "blocked by conflicts"
            assert any(action in each for each in dashboard.actions)
            assert dashboard.command.endswith("--no-change") is clean
            assert case.calls == 1 and b.environment.events == before
            assert b.reservations() == reservations and ports.conflicts.store.completed(case.record.key) == saved
            assert case.ports.merges.get(case.record.key.attempt_id) == work
            unchanged_input(b, target)
        stopped = land(ports, replace(request, minutes=None))
        assert isinstance(stopped, Failed) and stopped.word == ("refused:conflict" if clean else "refused:minutes")
        assert case.calls == 1 and b.environment.events == before
        assert b.reservations() == reservations and ports.conflicts.store.completed(case.record.key) == saved
        assert case.ports.merges.get(case.record.key.attempt_id) == work
        unchanged_input(b, target)


def test_running_resolution_is_retryable_and_restart_keeps_its_original_admission(b: LandBench) -> None:
    target = b.advance({"README": "current main\n"})
    ports, cases = executing(b, interrupt=True)
    request = LandRequest("tasks", "tl-1", b.repo.path, 5, accept=True)
    with pytest.raises(KeyboardInterrupt):
        land(ports, request)
    [case] = cases
    record = case.record
    case.interrupt, case.gone = False, False
    waiting = land(ports, replace(request, minutes=None))
    assert isinstance(waiting, Failed) and waiting.kind == "unavailable" and waiting.detail and case.calls == 1
    case.restart()
    b.con = case.con
    case.gone = True
    resumed = b.ports()
    resumed = replace(resumed, conflicts=replace(resumed.conflicts, execution=ports.conflicts.execution))
    finished = land(resumed, replace(request, minutes=None))
    assert isinstance(finished, Failed) and finished.word == "unavailable:running" and case.calls == 1
    finished = land(resumed, replace(request, minutes=None))
    assert isinstance(finished, Failed) and finished.word == "refused:minutes"
    work = case.ports.merges.get(record.key.attempt_id)
    assert work is not None and work.phase is Phase.COMPLETE and case.calls == 2
    assert case.record == record and b.reservations() == []
    unchanged_input(b, target)


def test_production_handoff_wiring_executes_over_the_existing_adapters(b: LandBench, monkeypatch: pytest.MonkeyPatch) -> None:
    target = b.advance({"README": "current main\n"})
    b.land()
    [record] = b.conflict_runs
    work, cases = b.checking(), list[ExecutionCase]()

    def remotes(_self: GitViews, path: Path, *, git_dir: Path | None = None) -> Repo:
        return b.views(path, git_dir=git_dir)

    def execution(ports: ExecutionPorts, key: AttemptKey) -> Result:
        assert ports.credentials == ("/bin/codex", {}) and ports.probe
        assert ports.environment is work.preparation and ports.files is work.slot_files and ports.evidence is work.files
        case = ExecutionCase(b.root / "factory.db", b.con, record, ports, b.slot, b.environment)
        cases.append(case)
        return execute(replace(ports, run=case.run), key)

    monkeypatch.setattr(GitViews, "remotes", remotes)
    monkeypatch.setattr("taskloop.land_conflict.composition.machine_credentials", lambda _h: ("/bin/codex", {}))
    monkeypatch.setattr("taskloop.land_conflict.composition.worker_gone", lambda _worker: True)
    monkeypatch.setattr("taskloop.land_conflict.composition.execute", execution)
    ports = replace(b.ports(), conflicts=conflict_handoff(work, GitViews(5), b.heartbeat_for))
    result = land(ports, LandRequest("tasks", "tl-1", b.repo.path, None, accept=True))
    assert isinstance(result, Failed) and result.word == "refused:minutes"
    assert len(cases) == 1 and cases[0].calls == 1
    monkeypatch.setattr("taskloop.land_conflict.composition.machine_credentials", lambda _h: pytest.fail("reacquired credentials"))
    assert land(ports, LandRequest("tasks", "tl-1", b.repo.path, None, accept=True)) == result
    unchanged_input(b, target)
