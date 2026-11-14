"""Stop attribution through execution, intact-DB reopen, hold discussion and the shared status readers."""

from pathlib import Path

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, StopIntent, Summary
from any_agent.procs import StopReport, Worker
from any_agent.procs import Survivor as ProcessSurvivor
from any_agent.supervisor import EntrySignal
from any_agent.testing import FakeRun
from sqlite_store import Store
from test_attempt import ENTRY, KEY, WORKER, AttemptSurroundings, app, database
from test_attempt import surroundings as attempt_surroundings
from test_slot_release import Ports, head

from taskloop.agents.stop_models import StopCause, StopPhase
from taskloop.agents.stop_store import StopStore
from taskloop.agents.stop_text import stop_text
from taskloop.attempt_status import Shown, StatusPorts, list_attempts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.dash_board import card_of
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.hold_facts import facts
from taskloop.hold_store import HoldInsert, HoldStore
from taskloop.hold_text import Returned, comment
from taskloop.operations import Failed
from taskloop.result_data import as_data
from taskloop.slot_release import NotReleased, Released
from taskloop.step_render import human

surroundings = attempt_surroundings


@pytest.mark.parametrize("timed_out,escalated,recorded", [(True, False, True), (True, True, True), (False, False, False)])
def test_hold_cause_is_identical_in_tracker_cli_and_dashboard(
    surroundings: AttemptSurroundings, timed_out: bool, escalated: bool, recorded: bool,
) -> None:
    con = database(surroundings)
    con.execute("UPDATE attempt SET label='auto'")
    rc = -9 if escalated else -15
    raw = RunOutcome(rc=rc, timed_out=timed_out, worker=WORKER, summary=Summary(rc=rc))
    registration = FakeRun(raw)

    def execute(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        result = registration(harness, spec, timeout, hooks)
        assert hooks is not None and hooks.before_stop is not None and hooks.after_stop is not None
        assert hooks.unattended is False
        if recorded:
            intent = StopIntent(worker=WORKER, reason="timeout")
            hooks.before_stop(intent)
            assert not con.in_transaction
            hooks.after_stop(intent, StopReport(term_sent=True, term_delivered=True,
                                              kill_sent=escalated, kill_delivered=escalated))
        return result

    result = app(con, surroundings, execute).execute(KEY, ENTRY)
    assert result.reason == ("run:timeout" if timed_out else "run:killed")
    reader = AttemptStore(lambda: con)
    row = HoldStore(lambda: con).insert(HoldInsert(KEY.attempt_id, KEY.attempt_id, f"failed:{result.reason}", 20))
    agent = reader.attempts()[0]
    files = EvidenceFiles(surroundings.tmp)
    held = facts(files, reader, row, "moved", agent, ())
    sentence = stop_text(held.stop, rc)
    assert sentence is not None and sentence in comment(held, Returned("unclaimed"))
    ports = StatusPorts(reader, lambda _entry: "gone", lambda: 30, lambda _key: None, lambda: "boot")
    shown = show_attempt(ports, surroundings.tmp, "tasks", "tl-1")
    assert isinstance(shown, Shown)
    assert sentence in "\n".join(human("show", shown, None)) and as_data(shown)["stop_cause"] == sentence
    assert "dispatch_token" not in str(as_data(shown)["agent_stop"])
    card = card_of(shown.view, agent, "Task", files, 30)
    assert card.hold_cause == sentence
    if recorded:
        assert held.stop is not None and held.stop.cause == StopCause.DEADLINE
    else:
        assert "no recorded sender" in sentence


@pytest.mark.parametrize("trigger", [1, 15])
def test_entry_interruption_persists_cause_before_normal_capture_and_survives_restart(
    admitted: Path, surroundings: AttemptSurroundings, trigger: int,
) -> None:
    con = Store(SCHEMA).open_rw(admitted)
    assert con is not None
    reader = AttemptStore(lambda: con)
    assert reader.register_entry(KEY, ENTRY, 10) == "accepted"
    con.execute("UPDATE attempt SET label='auto'")
    registration = FakeRun(RunOutcome(worker=WORKER))

    def execute(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        registration(harness, spec, timeout, hooks)
        assert hooks is not None and hooks.before_stop is not None and hooks.after_stop is not None
        intent = StopIntent(worker=WORKER, reason="entry_signal", trigger_signal=trigger)
        hooks.before_stop(intent)
        hooks.after_stop(intent, StopReport(term_sent=True, term_delivered=True))
        raise EntrySignal(trigger)

    with pytest.raises(SystemExit):
        app(con, surroundings, execute).execute(KEY, ENTRY)
    assert reader.collect(KEY) is None and not EvidenceFiles(surroundings.tmp).entry_log(KEY).exists()
    con.close()
    reopened = Store(SCHEMA).open_rw(admitted)
    assert reopened is not None
    try:
        reader = AttemptStore(lambda: reopened)
        row = HoldStore(lambda: reopened).insert(HoldInsert(KEY.attempt_id, KEY.attempt_id, "stuck:entry_lost", 20))
        agent = reader.attempts()[0]
        held = facts(EvidenceFiles(surroundings.tmp), reader, row, "moved", agent, ())
        sentence = stop_text(held.stop)
        assert sentence is not None and "sender of the entry signal is unknown" in sentence
        assert sentence in comment(held, Returned("unclaimed"))
        listed = list_attempts(StatusPorts(reader, lambda _entry: "gone", lambda: 30, lambda _key: None, lambda: "boot"))
        assert not isinstance(listed, Failed) and listed.attempts[0].stop == held.stop
        assert card_of(listed.attempts[0], agent, "Task", EvidenceFiles(surroundings.tmp), 30).hold_cause == sentence
        reopened.execute(
            """INSERT INTO attempt
            (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,access_policy,deadline,number,seq,slot_head)
            SELECT 'later','later-token',2,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
                   schema_version,model,effort,access_policy,deadline,1,seq+1,slot_head FROM attempt WHERE attempt_id='attempt'""",
        )
        reopened.execute("UPDATE reservation SET generation=2,attempt_id='later'")
        retained = facts(EvidenceFiles(surroundings.tmp), reader, row, "moved", agent, ())
        assert retained.stop == held.stop and sentence in comment(retained, Returned("unclaimed"))
        assert StopStore(lambda: reopened).get("later") is None
    finally:
        reopened.close()


@pytest.mark.parametrize("alive,seen", [(True, "gone"), (False, "unknown"), (False, "gone")])
def test_interrupted_intent_cannot_release_a_live_or_unknown_agent_and_recovery_never_relaunches(
    admitted: Path, surroundings: AttemptSurroundings, alive: bool, seen: str,
) -> None:
    con = Store(SCHEMA).open_rw(admitted)
    assert con is not None
    reader = AttemptStore(lambda: con)
    assert reader.register_entry(KEY, ENTRY, 10) == "accepted"
    registration = FakeRun(RunOutcome(worker=WORKER))

    def execute(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        registration(harness, spec, timeout, hooks)
        assert hooks is not None and hooks.before_stop is not None
        hooks.before_stop(StopIntent(worker=WORKER, reason="timeout"))
        raise RuntimeError("lost between intent and result")

    try:
        result = app(con, surroundings, execute).execute(KEY, ENTRY)
        assert result.status == "unavailable" and result.reason == "run_failed:RuntimeError"
        ports = Ports(con, surroundings.checkouts, surroundings.files, "unknown" if seen == "unknown" else "gone", alive)
        release = ports.releaser().release(KEY, abandon=True)
        record = StopStore(lambda: con).get(KEY.attempt_id)
        assert record is not None and record.proof is None
        if alive or seen == "unknown":
            assert isinstance(release, NotReleased) and record.phase == StopPhase.REQUESTED
            assert reader.slot_use().held and ports.unclaimed == []
        else:
            assert isinstance(release, Released) and record.phase == StopPhase.OBSERVED_GONE
            assert not reader.slot_use().held
        assert len(registration.calls) == 1
    finally:
        con.close()


def test_release_preserves_custody_of_a_recorded_survivor_after_the_leader_and_group_end(
    surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch,
) -> None:
    con = database(surroundings)
    con.execute("UPDATE attempt SET slot_head=?", (head(surroundings.slot),))
    registration = FakeRun(RunOutcome(rc=-15, timed_out=True, worker=WORKER, summary=Summary(rc=-15)))

    def execute(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        result = registration(harness, spec, timeout, hooks)
        assert hooks is not None and hooks.before_stop is not None and hooks.after_stop is not None
        intent = StopIntent(worker=WORKER, reason="timeout")
        hooks.before_stop(intent)
        hooks.after_stop(intent, StopReport(term_sent=True, term_delivered=True,
                                          survivors=[ProcessSurvivor(pid=43, start="survivor-start")]))
        return result

    assert app(con, surroundings, execute).execute(KEY, ENTRY).reason == "run:timeout"
    ports = Ports(con, surroundings.checkouts, surroundings.files)
    survivor_gone = False

    def gone(worker: Worker) -> bool:
        assert not con.in_transaction
        return worker.pid == WORKER.pid or survivor_gone

    monkeypatch.setattr(ports, "gone", gone)
    held = ports.releaser().release(KEY, abandon=True)
    assert isinstance(held, NotReleased) and held.reason == "worker_alive"
    assert ports.opens == ports.holds == 0 and ports.unclaimed == []
    assert AttemptStore(lambda: con).slot_use().held
    survivor_gone = True
    released = ports.releaser().release(KEY, abandon=True)
    assert isinstance(released, Released) and not AttemptStore(lambda: con).slot_use().held
