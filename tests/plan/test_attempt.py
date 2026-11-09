"""One authoritative admitted attempt, real SQLite and the owning semantic agent fake."""

import dataclasses
import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar, Literal

import pytest
from any_agent import CodexHarness, Harness, LaunchInputs, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from sqlite_store import Store, begin_immediate

from taskloop.composition import open_plan_attempts
from taskloop.plan import CODEX_ACCESS, CredentialsUnavailable, Execution, PlanAttempts, report
from taskloop.plan_files import PlanFiles
from taskloop.plan_schema import SCHEMA
from taskloop.plan_session import SessionLatch
from taskloop.plan_store import PlanStore, StoreRefused
from taskloop.plan_types import (
    Admission,
    AnswerState,
    AttemptKey,
    AttemptRecord,
    FileRef,
    PendingPlanResult,
    PlanAnswer,
    PublicationResult,
    Replaced,
    SessionInput,
)

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")  # the registered entry seeded below; execute runs only for it
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
PLAN = {"disposition": "planned", "plan_path": "docs/design/tl-1/plan.md", "commit": "a" * 40, "explanation": "Plan committed"}


def database(tmp_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.execute("PRAGMA foreign_keys=ON")
    with begin_immediate(con):
        for statement in SCHEMA.ddl.split(";"):
            if statement.strip():
                con.execute(statement)
        con.execute(f"PRAGMA user_version={SCHEMA.version}")
    return seed(con, tmp_path)


def seed(con: sqlite3.Connection, tmp_path: Path) -> sqlite3.Connection:
    """The authoritative prerequisites: an admitted, entry-registered attempt and its held reservation."""
    with begin_immediate(con):
        con.execute("INSERT INTO reservation VALUES ('slot','repo',?,1,'attempt')", (str(tmp_path),))
        digest = hashlib.sha256(b"Plan the actual task").hexdigest()
        con.execute(
            """INSERT INTO plan_attempt
            (attempt_id,dispatch_token,generation,adapter,backlog,task_id,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,sandbox,deadline,entry_pid,entry_start,entry_boot)
            VALUES ('attempt','dispatch',1,'beads','tasks','tl-1','repo','slot','input.txt',?,1,'chosen','high',
            'workspace-write',100,7,'entry-start','boot')""",
            (digest,),
        )
    (tmp_path / "input.txt").write_text("Plan the actual task")
    return con


def fake(answer: str | None = None, *, rc: int = 0, refs: tuple[str, ...] = ()) -> FakeRun:
    return FakeRun(
        RunOutcome(
            rc=rc,
            worker=WORKER,
            summary=Summary(
                text=json.dumps(PLAN) if answer is None else answer,
                rc=rc,
                stands=True,
                res={"ref": refs[-1] if refs else None, "tokens": {"in": 8, "cached": None, "out": 3}},
            ),
        ),
        refs=refs,
    )


def app(con: sqlite3.Connection, tmp_path: Path, execution: Execution) -> PlanAttempts:
    return PlanAttempts(
        PlanStore(lambda: con), PlanFiles(tmp_path), lambda: ("/bin/codex", {"SECRET": "credential"}), execution, lambda: 10
    )


def test_execute_and_independent_collection_preserve_facts_and_reservation(tmp_path: Path) -> None:
    con = database(tmp_path)
    execution = fake(refs=("native-session",))
    result = app(con, tmp_path, execution).execute(KEY, ENTRY)
    assert result.status == "collected"
    assert result.execution is not None
    assert result.execution.answer.kind == "valid"
    assert result.execution.facts.tokens == (8, None, 3)
    assert result.execution.facts.cost_usd is None
    assert result.execution.custody == "unresolved"
    assert con.execute("SELECT session_ref FROM plan_attempt").fetchone() == ("native-session",)
    other = fake()
    reader = app(con, tmp_path, other)
    assert reader.collect(KEY) == result
    assert reader.execute(KEY, ENTRY) == result
    assert not other.calls
    harness, spec, timeout, hooks = execution.calls[0]
    assert harness.kind == "codex" and spec.argv[1] == "exec"
    assert "chosen" in spec.argv and "workspace-write" in spec.argv
    assert "--output-schema" in spec.argv
    flags = spec.argv.index("--json")
    assert spec.argv[flags - len(CODEX_ACCESS) : flags] == list(CODEX_ACCESS)
    assert spec.env == {"SECRET": "credential"} and timeout == 90
    assert hooks is not None and hooks.unattended is False
    assert con.execute("SELECT count(*) FROM reservation").fetchone() == (1,)
    dump = "\n".join(con.iterdump())
    assert "credential" not in dump and "Plan committed" not in dump and "Plan the actual task" not in dump


@pytest.mark.parametrize(
    ("change", "status", "reason"),
    [
        ("missing", "refused", "absent"),
        ("stale", "refused", "stale_reservation"),
        ("entry", "refused", "unregistered_entry"),
        ("expired", "refused", "expired"),
        ("choices", "refused", "choices"),
        ("input", "refused", "input"),
        ("version", "unavailable", "store"),
    ],
)
def test_invalid_admission_never_executes(tmp_path: Path, change: str, status: str, reason: str) -> None:
    con = database(tmp_path)
    if change == "missing":
        con.execute("DELETE FROM plan_attempt")
    elif change == "stale":
        con.execute("UPDATE reservation SET generation=2")
    elif change == "entry":
        con.execute("UPDATE plan_attempt SET entry_boot=NULL")
    elif change == "expired":
        con.execute("UPDATE plan_attempt SET deadline=1")
    elif change == "choices":
        con.execute("UPDATE plan_attempt SET model=''")
    elif change == "input":
        (tmp_path / "input.txt").write_text("Changed")
    else:
        con.execute(f"PRAGMA user_version={SCHEMA.version + 1}")
    execution = fake()
    result = app(con, tmp_path, execution).execute(KEY, ENTRY)
    assert (result.status, result.reason) == (status, reason)
    assert execution.calls == []


def test_failed_execution_valid_answer_is_not_success(tmp_path: Path) -> None:
    con = database(tmp_path)
    result = app(con, tmp_path, fake(rc=7)).execute(KEY, ENTRY)
    assert result.execution is not None
    assert result.execution.facts.rc == 7
    assert result.execution.facts.reason == "worker_failed"
    assert result.execution.answer.kind == "valid"


@pytest.mark.parametrize("text, kind", [("", "missing"), ("not json", "json_invalid"), ('{"plan":3}', "schema_invalid")])
def test_bad_answer_has_one_execution(tmp_path: Path, text: str, kind: str) -> None:
    con = database(tmp_path)
    execution = fake(text)
    result = app(con, tmp_path, execution).execute(KEY, ENTRY)
    assert result.execution is not None and result.execution.answer.kind == kind
    assert len(execution.calls) == 1


def test_decoder_fault_leaves_captured_facts_and_can_resume_without_agent(tmp_path: Path) -> None:
    con = database(tmp_path)
    execution = fake()
    owner = app(con, tmp_path, execution)

    def broken(_value: object, _path: str) -> PlanAnswer:
        raise RuntimeError("decoder bug")

    owner.decoder = broken
    with pytest.raises(RuntimeError, match="decoder bug"):
        owner.execute(KEY, ENTRY)
    resumed, secrets = fake(), []
    reader = PlanAttempts(PlanStore(lambda: con), PlanFiles(tmp_path), lambda: secrets.append(1) or ("/bin/codex", {}), resumed, lambda: 10)
    captured = reader.collect(KEY)
    assert captured.status == "pending" and captured.execution is not None and captured.execution.answer.kind == "validation_pending"
    assert captured.execution.facts.rc == 0
    assert reader.execute(KEY, ENTRY).status == "collected"
    assert not resumed.calls and secrets == []


def test_dispatch_is_consumed_and_wrong_key_cannot_publish(tmp_path: Path) -> None:
    con = database(tmp_path)
    store = PlanStore(lambda: con)
    admitted = store.load(KEY)
    assert admitted is not None
    assert store.dispatch(admitted) == "accepted"
    assert store.dispatch(admitted) == "conflict"
    execution = fake()
    assert app(con, tmp_path, execution).execute(KEY, ENTRY).status == "pending"
    assert execution.calls == []
    assert app(con, tmp_path, fake()).collect(dataclasses.replace(KEY, dispatch_token="other")).status == "refused"


class Flaky:
    """Native SQLite that can go unavailable between operations, like a failing disk."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con, self.down = con, False

    def __call__(self) -> sqlite3.Connection | None:
        return None if self.down else self.con


def gated(run: FakeRun, flaky: Flaky, *, down_after_start: bool = False, probe: list[object] | None = None) -> Execution:
    """Wrap the released fake's hooks to observe live callbacks and to fail storage mid-run."""

    def call(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert hooks is not None and hooks.started is not None and hooks.ref is not None
        started, ref = hooks.started, hooks.ref

        def after_start(worker: Worker) -> None:
            started(worker)
            flaky.down = down_after_start

        def observed(value: str) -> None:
            ref(value)
            if probe is not None and not flaky.down:
                probe.append(flaky.con.execute("SELECT session_ref FROM plan_attempt").fetchone())

        return run(harness, spec, timeout, RunHooks(started=after_start, ref=observed, unattended=False))

    return call


def owner(flaky: Flaky, tmp_path: Path, execution: Execution, clock: Callable[[], float] = lambda: 10) -> PlanAttempts:
    return PlanAttempts(PlanStore(flaky), PlanFiles(tmp_path), lambda: ("/bin/codex", {}), execution, clock)


def test_live_ref_is_published_while_running_and_duplicates_are_idempotent(tmp_path: Path) -> None:
    flaky, probe = Flaky(database(tmp_path)), []
    run = fake(refs=("s", "s"))
    result = owner(flaky, tmp_path, gated(run, flaky, probe=probe)).execute(KEY, ENTRY)
    assert probe == [("s",), ("s",)]
    assert result.status == "collected" and result.execution is not None and result.execution.publication == "complete"


def test_absent_ref_stays_absent_and_late_reported_ref_is_published(tmp_path: Path) -> None:
    con = database(tmp_path)
    assert app(con, tmp_path, fake(refs=())).execute(KEY, ENTRY).execution is not None
    assert con.execute("SELECT session_ref FROM plan_attempt").fetchone() == (None,)
    con2 = database(tmp_path)
    late = FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), res={"ref": "late"})))
    result = app(con2, tmp_path, late).execute(KEY, ENTRY)
    assert result.execution is not None and result.execution.facts.session == "late"
    assert con2.execute("SELECT session_ref FROM plan_attempt").fetchone() == ("late",)


def test_conflicting_ref_is_recorded_not_overwritten(tmp_path: Path) -> None:
    con = database(tmp_path)
    result = app(con, tmp_path, fake(refs=("first", "second"))).execute(KEY, ENTRY)
    assert result.status == "conflict" and result.reason == "session"
    assert result.execution is not None and result.execution.answer.kind == "valid"
    assert con.execute("SELECT session_ref,session_conflict FROM plan_attempt").fetchone() == ("first", 1)


def test_storage_loss_keeps_first_ref_and_conflict_then_publish_retries(tmp_path: Path) -> None:
    flaky = Flaky(database(tmp_path))
    execution = fake(refs=("first", "second"))
    result = owner(flaky, tmp_path, gated(execution, flaky, down_after_start=True)).execute(KEY, ENTRY)
    assert (
        result.status == "unavailable"
        and result.pending is not None
        and flaky.con.execute("SELECT count(*) FROM plan_execution").fetchone() == (0,)
    )
    pending = result.pending
    assert pending.sessions == SessionInput("first", True, None) and pending.facts is not None and pending.facts.rc == 0
    assert pending.evidence is not None
    flaky.down = False
    retry = owner(flaky, tmp_path, fake())
    assert retry.publish(pending) == PublicationResult("accepted")
    assert retry.publish(pending) == PublicationResult("already_same")
    stored = retry.collect(KEY)
    assert stored.status == "conflict" and stored.execution is not None and stored.execution.answer.kind == "valid"
    assert flaky.con.execute("SELECT session_ref FROM plan_attempt").fetchone() == ("first",)


def test_publication_conflicts_on_different_facts_and_stale_publisher_cannot_rewrite(tmp_path: Path) -> None:
    flaky = Flaky(database(tmp_path))
    result = owner(flaky, tmp_path, gated(fake(), flaky, down_after_start=True)).execute(KEY, ENTRY)
    assert result.pending is not None
    flaky.down = False
    attempts = owner(flaky, tmp_path, fake())
    assert attempts.publish(result.pending) == PublicationResult("accepted")
    assert result.pending.facts is not None
    different = dataclasses.replace(result.pending, facts=dataclasses.replace(result.pending.facts, rc=9))
    assert attempts.publish(different) == PublicationResult("conflict")
    kept = attempts.collect(KEY).execution
    assert kept is not None and kept.facts.rc == 0


def test_unavailable_storage_refuses_without_agent_and_never_reports_missing(tmp_path: Path) -> None:
    flaky = Flaky(database(tmp_path))
    flaky.down = True
    execution = fake()
    attempts = owner(flaky, tmp_path, execution)
    assert attempts.execute(KEY, ENTRY).status == "unavailable" and attempts.collect(KEY).status == "unavailable"
    flaky.con.close()
    flaky.down = False
    assert attempts.execute(KEY, ENTRY).status == "unavailable" and execution.calls == []


def test_registration_gate_refuses_before_ref_or_result(tmp_path: Path) -> None:
    con = database(tmp_path)
    now = [10.0]
    inner = fake(refs=("s",))

    def late(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        now[0] = 500.0  # the deadline passes between the launch decision and the gate
        return inner(harness, spec, timeout, hooks)

    attempts = app(con, tmp_path, late)
    attempts.clock = lambda: now[0]
    result = attempts.execute(KEY, ENTRY)
    assert result.status == "refused" and result.reason == "expired"
    assert con.execute("SELECT phase,worker_pid,session_ref FROM plan_attempt").fetchone() == ("dispatching", None, None)
    assert con.execute("SELECT count(*) FROM plan_execution").fetchone() == (0,)


def test_reservation_change_after_dispatch_fences_registration(tmp_path: Path) -> None:
    con = database(tmp_path)

    def swap(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        con.execute("UPDATE reservation SET generation=2")
        return fake()(harness, spec, timeout, hooks)

    assert app(con, tmp_path, swap).execute(KEY, ENTRY).status == "refused"
    assert con.execute("SELECT count(*) FROM plan_execution").fetchone() == (0,)


def test_historical_collect_needs_no_reservation_input_or_deadline(tmp_path: Path) -> None:
    con = database(tmp_path)
    result = app(con, tmp_path, fake()).execute(KEY, ENTRY)
    con.execute("DELETE FROM reservation")  # test-only: collection must not depend on the live reservation
    (tmp_path / "input.txt").unlink()
    con.execute("UPDATE plan_attempt SET deadline=1")
    again = fake()
    assert app(con, tmp_path, again).collect(KEY) == result and app(con, tmp_path, again).execute(KEY, ENTRY) == result
    assert again.calls == []


def test_usage_unknown_is_not_zero_and_answer_grace_facts_are_kept(tmp_path: Path) -> None:
    con = database(tmp_path)
    grace = FakeRun(RunOutcome(rc=-15, stop="answer", worker=WORKER, summary=Summary(text=json.dumps(PLAN), stands=True, work=True)))
    facts = app(con, tmp_path, grace).execute(KEY, ENTRY).execution
    assert facts is not None and facts.facts.tokens is None and facts.facts.turns is None
    assert facts.facts.stop == "answer" and facts.facts.stands and facts.answer.kind == "valid"


def test_real_file_database_composition_opens_and_collects(tmp_path: Path) -> None:
    attempts = open_plan_attempts(tmp_path / "factory.db", tmp_path, lambda: ("/bin/codex", {}))
    assert attempts.collect(KEY).status == "refused"
    assert attempts.execute(KEY, ENTRY).status == "refused"
    assert (tmp_path / "factory.db").exists()


def test_run_failure_after_registration_is_typed_and_keeps_registered_state(tmp_path: Path) -> None:
    con = database(tmp_path)

    def crash(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert hooks is not None and hooks.started is not None
        hooks.started(WORKER)
        raise RuntimeError("library fault")

    result = app(con, tmp_path, crash).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("unavailable", "run_failed:RuntimeError")
    assert con.execute("SELECT phase,worker_pid FROM plan_attempt").fetchone() == ("registered", 42)
    assert app(con, tmp_path, fake()).execute(KEY, ENTRY).status == "pending"


def test_projection_fault_keeps_evidence_and_publish_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    con = database(tmp_path)

    def broken(_raw: RunOutcome) -> None:
        raise RuntimeError("projection bug")

    with monkeypatch.context() as patch:
        patch.setattr("taskloop.plan.execution_facts", broken)
        result = app(con, tmp_path, fake()).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("unavailable", "projection:RuntimeError")
    assert result.pending is not None and result.pending.facts is None and result.pending.evidence is not None
    assert (tmp_path / result.pending.evidence.answer.path).exists()
    attempts = app(con, tmp_path, fake())
    assert attempts.publish(result.pending) == PublicationResult("accepted")
    assert attempts.collect(KEY).status == "collected"


def test_stored_pending_publication_is_reconciled_by_execute(tmp_path: Path) -> None:
    con = database(tmp_path)
    late = FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), res={"ref": "late"})))
    assert app(con, tmp_path, late).execute(KEY, ENTRY).status == "collected"
    con.execute("UPDATE plan_execution SET publication='fault'")
    con.execute("UPDATE plan_attempt SET session_ref=NULL")
    again = fake()
    result = app(con, tmp_path, again).execute(KEY, ENTRY)
    assert result.status == "collected" and again.calls == []
    assert con.execute("SELECT session_ref FROM plan_attempt").fetchone() == ("late",)


@pytest.mark.parametrize(
    ("error", "reason"), [(OSError("keychain locked"), "credentials:OSError"), (CredentialsUnavailable("auth"), "credentials:auth")]
)
def test_credentials_failure_leaves_the_attempt_admitted_and_never_dispatches(tmp_path: Path, error: Exception, reason: str) -> None:
    con = database(tmp_path)

    def refuse() -> tuple[str, dict[str, str]]:
        raise error

    execution = fake()
    attempts = PlanAttempts(PlanStore(lambda: con), PlanFiles(tmp_path), refuse, execution, lambda: 10)
    for _ in range(2):
        result = attempts.execute(KEY, ENTRY)
        assert (result.status, result.reason) == ("unavailable", reason) and execution.calls == []
        assert con.execute("SELECT phase,rev FROM plan_attempt").fetchone() == ("admitted", 0)


def test_files_failure_is_typed_and_leaves_the_attempt_admitted(tmp_path: Path) -> None:
    con = database(tmp_path)
    (tmp_path / "attempts").write_text("a file where the artifact folder belongs")
    execution = fake()
    result = app(con, tmp_path, execution).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("unavailable", "files") and execution.calls == []
    assert con.execute("SELECT phase FROM plan_attempt").fetchone() == ("admitted",)


@pytest.mark.parametrize("me", [(8, "entry-start", "boot"), (7, "other-start", "boot"), (7, "entry-start", "other-boot")])
def test_only_the_registered_entry_executes(tmp_path: Path, me: tuple[int, str, str]) -> None:
    con, execution, asked = database(tmp_path), fake(), []
    attempts = PlanAttempts(
        PlanStore(lambda: con), PlanFiles(tmp_path), lambda: asked.append(1) or ("/bin/codex", {}), execution, lambda: 10
    )
    result = attempts.execute(KEY, me)
    assert (result.status, result.reason) == ("refused", "not_entry")
    assert asked == [] and execution.calls == [] and not (tmp_path / "attempts").exists()
    assert con.execute("SELECT phase FROM plan_attempt").fetchone() == ("admitted",)


def test_only_the_workspace_write_sandbox_is_launched(tmp_path: Path) -> None:
    con, execution = database(tmp_path), fake()
    con.execute("UPDATE plan_attempt SET sandbox='danger-full-access'")
    result = app(con, tmp_path, execution).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("refused", "sandbox") and execution.calls == []
    assert con.execute("SELECT phase FROM plan_attempt").fetchone() == ("admitted",)


class Spy(CodexHarness):
    """The real Codex harness, counting cleanups; `broken` makes `launch_spec` fail."""

    cleanups: ClassVar[list[int]] = []
    broken: ClassVar[bool] = False

    def launch_spec(self, i: LaunchInputs) -> LaunchSpec:
        if Spy.broken:
            raise ValueError("bad launch")
        return super().launch_spec(i)

    def cleanup(self) -> None:
        Spy.cleanups.append(1)
        super().cleanup()


@pytest.mark.parametrize(
    ("case", "status", "reason", "phase"),
    [
        ("launch", "unavailable", "launch:ValueError", "admitted"),
        ("raced", "pending", "dispatching", "admitted"),
        ("store", "unavailable", "store", "admitted"),
        ("expired", "refused", "expired", "admitted"),  # crossed while resolving the launch: never dispatched
        ("run", "collected", "", "captured"),
    ],
)
def test_the_harness_is_cleaned_up_once_on_every_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, status: str, reason: str, phase: str
) -> None:
    flaky, now, execution = Flaky(database(tmp_path)), [10.0], fake()
    monkeypatch.setattr("taskloop.plan.CodexHarness", Spy)
    monkeypatch.setattr(Spy, "cleanups", [])
    monkeypatch.setattr(Spy, "broken", case == "launch")

    def credentials() -> tuple[str, dict[str, str]]:
        if case == "raced":  # another writer moves the row between load and dispatch
            flaky.con.execute("UPDATE plan_attempt SET rev=rev+1")
        flaky.down = case == "store"
        now[0] = 500.0 if case == "expired" else now[0]
        return "/bin/codex", {}

    def clock() -> float:
        return now[0]

    result = PlanAttempts(PlanStore(flaky), PlanFiles(tmp_path), credentials, execution, clock).execute(KEY, ENTRY)
    assert (result.status, result.reason) == (status, reason)
    assert Spy.cleanups == [1] and len(execution.calls) == (case == "run")
    assert flaky.con.execute("SELECT phase FROM plan_attempt").fetchone() == (phase,)


def test_the_registration_gate_writes_through_the_gate_store_only(tmp_path: Path) -> None:
    con = database(tmp_path)

    class Main(PlanStore):
        def register(self, admission: Admission, worker: Worker) -> Literal["accepted", "already_same", "conflict"]:
            raise AssertionError("the harness registration must use the bounded gate store")

    gate = PlanStore(lambda: con)
    attempts = PlanAttempts(Main(lambda: con), PlanFiles(tmp_path), lambda: ("/bin/codex", {}), fake(), lambda: 10, gate=gate)
    assert attempts.execute(KEY, ENTRY).status == "collected"
    assert con.execute("SELECT phase,worker_pid FROM plan_attempt").fetchone() == ("captured", 42)


def test_the_gate_connection_is_opened_before_dispatch_and_its_fault_leaves_admitted(tmp_path: Path) -> None:
    con, events = database(tmp_path), []

    class Main(PlanStore):
        def dispatch(self, expected: AttemptRecord) -> Literal["accepted", "conflict"]:
            events.append("dispatch")
            return super().dispatch(expected)

    def opened() -> sqlite3.Connection | None:
        events.append("gate")
        return con

    attempts = PlanAttempts(Main(lambda: con), PlanFiles(tmp_path), lambda: ("/bin/codex", {}), fake(), lambda: 10, gate=PlanStore(opened))
    assert attempts.execute(KEY, ENTRY).status == "collected"
    assert events[:2] == ["gate", "dispatch"]
    con2, run = database(tmp_path), fake()
    broken = PlanAttempts(
        Main(lambda: con2), PlanFiles(tmp_path), lambda: ("/bin/codex", {}), run, lambda: 10, gate=PlanStore(lambda: None)
    )
    result = broken.execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("unavailable", "store") and run.calls == []
    assert con2.execute("SELECT phase FROM plan_attempt").fetchone() == ("admitted",)


def test_an_entry_replaced_between_load_and_dispatch_fences_the_dispatch(tmp_path: Path) -> None:
    con, run = database(tmp_path), fake()
    store = PlanStore(lambda: con)

    def replacing() -> tuple[str, dict[str, str]]:
        assert store.register_entry(KEY, (9, "new-start", "boot"), 10, Replaced(ENTRY, "gone")) == "accepted"
        return "/bin/codex", {}

    result = PlanAttempts(store, PlanFiles(tmp_path), replacing, run, lambda: 10).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("refused", "changed_admission") and run.calls == []
    assert con.execute("SELECT phase,entry_pid FROM plan_attempt").fetchone() == ("admitted", 9)


def test_composition_bounds_only_the_gate_connection(tmp_path: Path) -> None:
    attempts = open_plan_attempts(tmp_path / "factory.db", tmp_path, lambda: ("/bin/codex", {}))
    gate, main = attempts.gate.connect(), attempts.store.connect()
    assert gate is not None and main is not None and gate is not main
    assert gate.execute("PRAGMA busy_timeout").fetchone() == (1500,)
    assert main.execute("PRAGMA busy_timeout").fetchone() == (5000,)


def pending_result(tmp_path: Path) -> tuple[Flaky, PlanAttempts, PendingPlanResult]:
    flaky = Flaky(database(tmp_path))
    result = owner(flaky, tmp_path, gated(fake(), flaky, down_after_start=True)).execute(KEY, ENTRY)
    assert result.pending is not None and result.pending.facts is not None
    flaky.down = False
    return flaky, owner(flaky, tmp_path, fake()), result.pending


def test_capture_upgrades_pending_publication_once_and_rejects_different_evidence(tmp_path: Path) -> None:
    flaky, _attempts, pending = pending_result(tmp_path)
    store = PlanStore(flaky)
    loaded = store.load(KEY)
    assert loaded is not None and pending.facts is not None and pending.evidence is not None
    admission = loaded.admission
    assert store.capture(admission, None, pending.facts, pending.evidence, "pending") == "accepted"
    assert store.capture(admission, None, pending.facts, pending.evidence, "pending") == "already_same"
    assert store.capture(admission, None, pending.facts, pending.evidence, "complete") == "accepted"
    assert store.capture(admission, None, pending.facts, pending.evidence, "complete") == "already_same"
    assert store.capture(admission, None, pending.facts, pending.evidence, "pending") == "already_same"
    other = dataclasses.replace(pending.evidence, stdout=FileRef("elsewhere", "0" * 64))
    assert store.capture(admission, None, pending.facts, other, "complete") == "conflict"
    attempts = owner(flaky, tmp_path, fake())
    assert attempts.publish(dataclasses.replace(pending, evidence=other)) == PublicationResult("conflict")


def test_answer_summary_is_idempotent_and_never_replaced(tmp_path: Path) -> None:
    flaky, attempts, pending = pending_result(tmp_path)
    assert attempts.publish(pending) == PublicationResult("accepted")
    store = PlanStore(flaky)
    loaded = store.load(KEY)
    assert loaded is not None and pending.evidence is not None
    same = AnswerState("valid", "planned", "docs/design/tl-1/plan.md", "a" * 40)
    assert store.answer(loaded.admission, pending.evidence, same) == "already_same"
    assert store.answer(loaded.admission, pending.evidence, AnswerState("missing")) == "conflict"
    assert store.answer(loaded.admission, dataclasses.replace(pending.evidence, stderr=FileRef("x", "0" * 64)), same) == "conflict"


def test_ref_callback_on_another_thread_uses_its_own_shared_writer_connection(tmp_path: Path) -> None:
    store = Store(SCHEMA)
    path = tmp_path / "factory.db"
    seeded = store.open_rw(path)
    assert seeded is not None
    seed(seeded, tmp_path)
    inner = FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN))))  # reports no ref: only the thread can publish
    seen: list[int] = []

    def threaded(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert hooks is not None and hooks.ref is not None
        ref = hooks.ref
        worker = threading.Thread(target=lambda: (ref("threaded"), seen.append(threading.get_ident())))
        quiet = RunHooks(started=hooks.started, ref=None, unattended=False)
        outcome = inner(harness, spec, timeout, quiet)
        worker.start()
        worker.join()
        return outcome

    attempts = PlanAttempts(
        PlanStore(lambda: store.shared_rw(path), store.begin_immediate),
        PlanFiles(tmp_path),
        lambda: ("/bin/codex", {}),
        threaded,
        lambda: 10,
    )
    assert attempts.execute(KEY, ENTRY).status == "collected"
    assert seen and seen != [threading.get_ident()]
    assert seeded.execute("SELECT session_ref FROM plan_attempt").fetchone() == ("threaded",)
    store.close_shared()


def test_two_connections_contend_for_one_dispatch(tmp_path: Path) -> None:
    store = Store(SCHEMA)
    path = tmp_path / "factory.db"
    first = store.open_rw(path)
    assert first is not None
    seed(first, tmp_path)
    record = PlanStore(lambda: first).load(KEY)
    assert record is not None
    barrier, outcomes = threading.Barrier(2), []

    def contender() -> None:
        mine = Store(SCHEMA).open_rw(path)
        barrier.wait()
        outcomes.append(PlanStore(lambda: mine, store.begin_immediate).dispatch(record))

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["accepted", "conflict"]


def test_stored_pending_publication_is_not_promoted_without_evidence(tmp_path: Path) -> None:
    con = database(tmp_path)
    assert app(con, tmp_path, fake()).execute(KEY, ENTRY).status == "collected"  # the summary reports no ref: facts.session is None
    con.execute("UPDATE plan_execution SET publication='pending'")
    again = fake()
    attempts = app(con, tmp_path, again)
    for _ in range(2):
        result = attempts.execute(KEY, ENTRY)
        assert (result.status, result.reason) == ("pending", "session_pending") and again.calls == []
    assert con.execute("SELECT publication FROM plan_execution").fetchone() == ("pending",)
    con.execute("UPDATE plan_attempt SET session_ref='accepted'")
    assert attempts.execute(KEY, ENTRY).status == "collected"
    con.execute("UPDATE plan_execution SET publication='fault'")
    con.execute("DELETE FROM reservation")  # a released reservation: execute on a non-terminal stored state refuses, collect still reads
    assert (attempts.execute(KEY, ENTRY).status, attempts.execute(KEY, ENTRY).reason) == ("refused", "stale_reservation")
    assert attempts.collect(KEY).reason == "session_fault"


def test_recorded_session_conflict_is_visible_without_a_result_and_blocks_complete(tmp_path: Path) -> None:
    flaky, attempts, pending = pending_result(tmp_path)
    flaky.con.execute("UPDATE plan_attempt SET session_ref='first',session_conflict=1")
    assert (attempts.collect(KEY).status, attempts.collect(KEY).reason) == ("conflict", "session")
    assert attempts.publish(pending).status == "accepted"
    assert flaky.con.execute("SELECT publication FROM plan_execution").fetchone() == ("conflict",)


def test_registration_conflict_and_same_identity_are_distinguished(tmp_path: Path) -> None:
    con = database(tmp_path)
    inner = fake()

    def twice(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert hooks is not None and hooks.started is not None
        hooks.started(WORKER)
        return inner(harness, spec, timeout, hooks)  # the same identity again: already_same, not an error

    assert app(con, tmp_path, twice).execute(KEY, ENTRY).status == "collected"


def test_different_worker_identity_refuses_registration_before_exec(tmp_path: Path) -> None:
    con = database(tmp_path)

    def different(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert hooks is not None and hooks.started is not None
        hooks.started(WORKER)
        hooks.started(dataclasses.replace(WORKER, pid=43))
        raise AssertionError("exec must stay gated")

    result = app(con, tmp_path, different).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("conflict", "registration_conflict")


@pytest.mark.parametrize(
    ("error", "fault"),
    [(RuntimeError("bug"), "unexpected:RuntimeError"), (StoreRefused("stale_reservation"), "refused:stale_reservation")],
)
def test_ref_callback_faults_are_retained_with_cause_and_never_raised(tmp_path: Path, error: Exception, fault: str) -> None:
    con = database(tmp_path)
    loaded = PlanStore(lambda: con).load(KEY)
    assert loaded is not None

    class Broken(PlanStore):
        def session(self, admission: Admission, ref: str) -> Literal["accepted", "already_same", "conflict"]:
            raise error

    latch = SessionLatch(Broken(lambda: con), loaded.admission)
    latch.observe("ref")
    assert latch.snapshot() == SessionInput("ref", False, fault)


def test_report_never_presents_pending_state_as_collected(tmp_path: Path) -> None:
    result = app(database(tmp_path), tmp_path, fake()).execute(KEY, ENTRY)
    stored = result.execution
    assert stored is not None and report(stored).status == "collected"
    for publication, status, reason in (
        ("pending", "pending", "session_pending"),
        ("fault", "pending", "session_fault"),
        ("conflict", "conflict", "session"),
    ):
        shown = report(dataclasses.replace(stored, publication=publication))
        assert (shown.status, shown.reason) == (status, reason)
    waiting = report(dataclasses.replace(stored, answer=AnswerState("validation_pending")))
    assert (waiting.status, waiting.reason) == ("pending", "validation_pending")
