"""Deterministic drain interleavings at the existing admission, dispatch, rounds and land boundaries."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome
from doubles import CHECKS, ChecksBench, Command, Done, FakeSlotFiles, PinnedViews
from git_porcelain.testing import FakeRepo, FakeWorktree
from land_bench import LandBench, bench
from round_bench import Factory, scripts, task
from round_bench import Tracker as RoundTracker
from sqlite_store import Store
from test_admit import Tracker, admission, request, rows, slots
from test_checks import CHECK, TEST
from test_checks import Bench as ChecksBlock
from test_land_push import lost
from test_launch import FakeStart, launcher
from test_round import REQUEST, Bench
from test_verifier import KEY, P, agent, attempts, verifier

from taskloop.admit import AdmitRefused, Admitted
from taskloop.admit_chain import ChainAdmission, NextAdmission, NextStepRequest, RepeatRequest
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey, FileRef, Verified
from taskloop.check_repeat.feedback import Availability, FailedCheck, OutputTail
from taskloop.check_repeat.store import CheckRepeatStore
from taskloop.check_store import CheckStore
from taskloop.drain.composition import open_drain
from taskloop.drain.drain import Ports, inspect
from taskloop.drain.models import ActionKind, Conclusion, Reason, Seen, State
from taskloop.drain.observe import identity
from taskloop.drain.reconcile import Reconcile
from taskloop.drain.store import DrainStore
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.land import Landed
from taskloop.land_store import LandStore
from taskloop.launch import Launched, LaunchRefused
from taskloop.operations import Failed
from taskloop.round import run_round


def test_fresh_admission_fenced_before_claim_touches_no_tracker(
    factory: sqlite3.Connection,
    repo: FakeRepo,
    root: Path,
    tmp_path: Path,
) -> None:
    slots(factory, repo, root, 1)
    tracker = Tracker(factory, tmp_path / "artifacts")
    DrainStore(lambda: factory).request()
    found = admission(factory, tmp_path, tracker, repo).admit(request(tmp_path, repo))
    assert isinstance(found, AdmitRefused) and found.reason is Reason.DRAINING
    assert rows(factory) == (0, 0) and tracker.calls == []


def test_drain_during_tracker_claim_releases_only_that_intent_without_admitting(
    factory: sqlite3.Connection,
    repo: FakeRepo,
    root: Path,
    tmp_path: Path,
) -> None:
    slots(factory, repo, root, 1)
    tracker = Tracker(factory, tmp_path / "artifacts")
    gate = DrainStore(lambda: factory)

    def during() -> None:
        assert len(gate.pending()) == 1 and gate.pending()[0].kind is ActionKind.CLAIM
        gate.request()
        assert not gate.complete(1)

    tracker.during = during
    found = admission(factory, tmp_path, tracker, repo).admit(request(tmp_path, repo))
    assert isinstance(found, AdmitRefused) and found.reason is Reason.DRAINING
    assert rows(factory) == (0, 0) and tracker.calls == ["claim:tl-1", "unclaim:tl-1"]
    assert not gate.pending() and gate.boundary().state is State.DRAINING


def test_drain_after_admission_preserves_attempt_reservation_and_claim(
    factory: sqlite3.Connection,
    repo: FakeRepo,
    root: Path,
    tmp_path: Path,
) -> None:
    slots(factory, repo, root, 1)
    tracker = Tracker(factory, tmp_path / "artifacts")
    found = admission(factory, tmp_path, tracker, repo).admit(request(tmp_path, repo))
    assert isinstance(found, Admitted)
    gate = DrainStore(lambda: factory)
    gate.request()
    assert gate.complete(1)  # safely admitted, no dispatch authorization or registered entry
    assert rows(factory) == (1, 1) and tracker.calls == ["claim:tl-1"]


@pytest.mark.parametrize("before_authorization", [False, True])
def test_dispatch_and_child_registration_are_ordered_against_drain(admitted: Path, before_authorization: bool) -> None:
    con = Store(SCHEMA).open_rw(admitted)
    assert con is not None
    try:
        gate = DrainStore(lambda: con)
        observed: list[Conclusion] = []

        def before_callback() -> None:
            gate.request()
            assert len(gate.pending()) == 1
            with open_drain(admitted) as ports:
                assert isinstance(ports, Ports)
                observed.append(inspect(replace(ports, observe=lambda _owner: Seen.ALIVE), 1).conclusion)

        started = FakeStart(before=before_callback)
        if before_authorization:
            gate.request()
        result = launcher(admitted, started).launch("tasks", "tl-1", 30)
        if before_authorization:
            assert isinstance(result, LaunchRefused) and result.reason is Reason.DRAINING and not started.calls
        else:
            assert isinstance(result, Launched) and started.permitted and observed == [Conclusion.WAITING]
            assert con.execute("SELECT entry_pid FROM attempt").fetchone() == (9,)
            assert not gate.pending()
        assert gate.boundary().state is State.DRAINING
    finally:
        con.close()


def test_direct_registration_without_dispatch_authorization_is_fenced(admitted: Path) -> None:
    con = Store(SCHEMA).open_rw(admitted)
    assert con is not None
    try:
        gate = DrainStore(lambda: con)
        gate.request()
        result = AttemptStore(lambda: con).register_entry(AttemptKey("attempt", "dispatch", 1), (51, "entry", "boot"), 10)
        assert result == "refused" and con.execute("SELECT entry_pid FROM attempt").fetchone() == (None,)
    finally:
        con.close()


def test_repeat_and_failed_check_repair_cannot_create_an_attempt_behind_the_fence(
    factory: sqlite3.Connection,
    tmp_path: Path,
) -> None:
    DrainStore(lambda: factory).request()
    key = AttemptKey("previous", "token", 1)
    chain = ChainAdmission(lambda: factory, Store(SCHEMA).begin_immediate, EvidenceFiles(tmp_path), lambda: 10)
    found = chain.admit_repeat(RepeatRequest(key, "repeat", 100, "uncommitted"))
    assert isinstance(found, AdmitRefused) and found.reason is Reason.DRAINING
    source = AttemptKey("checks", "checks-token", 1)
    feedback = FailedCheck(
        source=source,
        block=1,
        commit="a" * 40,
        name="test",
        argv=("just", "test"),
        rc=1,
        output=OutputTail(availability=Availability.UNAVAILABLE),
    )
    repair = CheckRepeatStore(lambda: factory).admit(
        key, feedback, AttemptKey("next", "next-token", 2), FileRef("input", "d" * 64), (), 100
    )
    assert isinstance(repair, AdmitRefused) and repair.reason is Reason.DRAINING
    assert rows(factory) == (0, 0)


@pytest.mark.parametrize("rerun", [False, True])
def test_checks_admission_and_rerun_recheck_the_fence_in_the_commit_transaction(
    done: Done,
    repo: FakeRepo,
    checkouts: PinnedViews,
    slot_files: FakeSlotFiles,
    rerun: bool,
) -> None:
    checking = ChecksBench(done, repo, checkouts, slot_files)
    try:
        if rerun:
            assert isinstance(checking.admit(), Admitted)
            checking.concluded()
        before = checking.stored()
        checking.racing = lambda: DrainStore(lambda: checking.con).request()
        result = checking.admit(2 if rerun else 1)
        assert isinstance(result, AdmitRefused) and result.reason is Reason.DRAINING
        assert checking.stored() == before
    finally:
        checking.con.close()


def test_rounds_and_one_shot_rounds_do_no_work_after_the_fence(factory: sqlite3.Connection) -> None:
    scheduling = Bench(factory)
    DrainStore(lambda: factory).request()
    result = run_round(scheduling.ports(), REQUEST)
    assert isinstance(result, Failed) and result.reason is Reason.DRAINING
    assert scheduling.admission.requests == scheduling.launcher.calls == []


def test_land_fenced_before_start_creates_no_candidate_or_push(tmp_path: Path) -> None:
    landing = bench(tmp_path)
    DrainStore(lambda: landing.con).request()
    result = landing.land()
    assert isinstance(result, Failed) and result.reason is Reason.DRAINING
    assert landing.rows() == () and landing.repo.pushes == 0 and not landing.execs()


def test_land_authorized_before_drain_finishes_validation_and_push(tmp_path: Path) -> None:
    landing: LandBench = bench(tmp_path)
    landing.advance({"OTHER": "another task\n"})
    gate = DrainStore(lambda: landing.con)

    def during_validation() -> None:
        assert any(action.kind is ActionKind.LAND for action in gate.pending())
        gate.request()
        assert not gate.complete(1)

    landing.racing = during_validation
    result = landing.land()
    assert isinstance(result, Landed) and result.row.validation == "passed" and result.how == "pushed"
    assert not gate.pending() and gate.boundary().state is State.DRAINING
    assert landing.reservations() == [] and landing.repo.pushes == 1


def test_lost_push_result_is_observed_and_recorded_without_pushing_again(tmp_path: Path) -> None:
    landing = bench(tmp_path)
    commit = lost(landing)
    gate = DrainStore(lambda: landing.con)
    assert gate.pending() and landing.rows()[0].delivery is None
    reconcile = Reconcile(
        AttemptStore(lambda: landing.con), LandStore(lambda: landing.con), landing.views, landing.inspect, lambda _action: False, lambda: 20
    )
    action = gate.pending()[0]
    gate.request()
    assert reconcile(action)
    assert landing.rows()[0].delivery == "pushed" and landing.rows()[0].remote_head == commit
    assert landing.repo.pushes == 1 and landing.tracker == []  # no new land or tracker close


def test_an_authorized_agent_body_can_capture_and_finalize_after_drain(
    registered: sqlite3.Connection,
    tmp_path: Path,
    slot: FakeWorktree,
    checkouts: PinnedViews,
    slot_files: FakeSlotFiles,
) -> None:
    me = identity()
    assert me is not None
    entry = me.pid, me.start, me.boot
    registered.execute("UPDATE attempt SET entry_pid=?,entry_start=?,entry_boot=?", entry)
    body = agent(slot, {P: "# Plan\n"})

    def running(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        DrainStore(lambda: registered).request()
        return body(harness, spec, timeout, hooks)

    result = attempts(registered, tmp_path, checkouts, slot_files, running).execute(KEY, entry)
    assert result.status == "pending" and result.reason == "verification"
    assert registered.execute("SELECT phase FROM attempt").fetchone() == ("captured",)
    assert isinstance(verifier(registered, checkouts, slot_files).verify(KEY), Verified)
    assert registered.execute("SELECT count(*) FROM attempt").fetchone() == (1,)
    assert DrainStore(lambda: registered).boundary().state is State.DRAINING


def test_existing_checks_attempt_finishes_its_remaining_checks_after_the_fence(
    checking: sqlite3.Connection,
    slot: FakeWorktree,
    checkouts: PinnedViews,
    tmp_path: Path,
) -> None:
    block = ChecksBlock(checking, slot, checkouts, tmp_path)
    gate = DrainStore(lambda: checking)
    block.process.script = [Command(effect=gate.request), Command()]
    assert block.run(CHECK, TEST) is None
    CheckStore(lambda: checking).conclude(CHECKS, "passed", None, 20)
    assert [(row[2], row[3]) for row in block.rows()] == [("check", "passed"), ("test", "passed")]
    assert checking.execute("SELECT phase,conclusion FROM checks_attempt").fetchone() == ("concluded", "passed")
    assert gate.boundary().state is State.DRAINING


def test_next_agent_step_rechecks_drain_at_its_committing_transaction(
    factory: sqlite3.Connection,
    tmp_path: Path,
    slot: FakeWorktree,
    checkouts: PinnedViews,
    slot_files: FakeSlotFiles,
) -> None:
    built = Factory(factory, tmp_path, slot, checkouts, slot_files, RoundTracker(task("tl-1")))
    scripts(built, slot, "tl-1")
    built.by_hand("tl-1")
    previous = built.store.attempts("tasks", "tl-1")[0].key
    advance = built.starting().advance
    assert isinstance(advance, NextAdmission)
    original = advance.begin

    def fence(con: sqlite3.Connection):
        DrainStore(lambda: con).request()
        return original(con)

    advance.begin = fence
    found = advance.admit_next(NextStepRequest(previous, slot.repo.path, "m", "high", "workspace-write", 100))
    assert isinstance(found, AdmitRefused) and found.reason is Reason.DRAINING
    assert factory.execute("SELECT count(*) FROM attempt").fetchone() == (1,)
    assert factory.execute("SELECT * FROM reservation").fetchall() == []
    assert built.tracker.claims == ["tl-1"]
