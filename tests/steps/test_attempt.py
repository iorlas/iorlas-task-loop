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
from git_porcelain.testing import FakeWorktree
from sqlite_store import Store, begin_immediate

from taskloop.agents.launch import AgentLaunch, CredentialReason, Credentials, CredentialsUnavailable, codex_access
from taskloop.agents.settings import CodexPolicy
from taskloop.attempt import Attempts, Execution
from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_result import report
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import (
    DEFAULT_GIT_READ_SECONDS,
    Admission,
    Answer,
    AnswerState,
    AttemptKey,
    AttemptRecord,
    CaptureResult,
    Checkouts,
    EntryIdentity,
    FileRef,
    PendingResult,
    Replaced,
    SessionInput,
    SlotFiles,
    StepRules,
)
from taskloop.command_sink import WatchedHooks
from taskloop.composition import open_attempts
from taskloop.evidence_files import EvidenceFiles
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.harness_choice import HarnessKind
from taskloop.ids import NativeIds
from taskloop.session import SessionLatch
from taskloop.steps import kind

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")  # the registered entry seeded below; execute runs only for it
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "Plan committed"}
BASE = "b" * 40  # a recorded B for store-level dispatches; the body reads the slot's own HEAD


def codex(_harness: HarnessKind) -> tuple[str, dict[str, str]]:
    return "/bin/codex", {}


@dataclasses.dataclass(frozen=True)
class AttemptSurroundings:
    """The admitted attempt's surroundings: the artifacts root, its clean detached slot, and the one Attempts builder."""

    tmp: Path
    slot: FakeWorktree
    checkouts: Checkouts
    files: SlotFiles

    def attempts(
        self,
        store: AttemptStore,
        execution: Execution,
        *,
        credentials: Credentials = codex,
        clock: Callable[[], float] = lambda: 10,
        registration_store: AttemptStore | None = None,
    ) -> Attempts:
        return Attempts(
            store, EvidenceFiles(self.tmp), AgentLaunch(credentials, ids=NativeIds()), execution, clock, self.checkouts, self.files,
            registration_store=registration_store,
        )


@pytest.fixture
def surroundings(tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, slot_files: SlotFiles) -> AttemptSurroundings:
    return AttemptSurroundings(tmp_path, slot, checkouts, slot_files)


def database(surroundings: AttemptSurroundings) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.execute("PRAGMA foreign_keys=ON")
    with begin_immediate(con):
        for statement in SCHEMA.ddl.split(";"):
            if statement.strip():
                con.execute(statement)
        con.execute(f"PRAGMA user_version={SCHEMA.version}")
    return seed(con, surroundings)


def seed(con: sqlite3.Connection, surroundings: AttemptSurroundings) -> sqlite3.Connection:
    """The authoritative prerequisites: an admitted, entry-registered attempt on the clean slot and its held reservation."""
    repo_id = surroundings.slot.repo.identity().key
    with begin_immediate(con):
        con.execute("INSERT INTO slot (repo_id,name,path) VALUES (?,'s1',?)", (repo_id, str(surroundings.slot.path)))
        con.execute("INSERT INTO reservation VALUES ('s1',?,1,'attempt')", (repo_id,))
        digest = hashlib.sha256(b"Plan the actual task").hexdigest()
        con.execute(
            """INSERT INTO attempt
            (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
             schema_version,model,effort,access_policy,deadline,entry_pid,entry_start,entry_boot,number,seq,slot_head)
            VALUES ('attempt','dispatch',1,'plan','beads','tasks','tl-1','/tracker',?,'s1','input.txt',?,1,'chosen','high',
            '{"harness":"codex","sandbox":"workspace-write"}',100,7,'entry-start','boot',1,1,'dddddddddddddddddddddddddddddddddddddddd')""",
            (repo_id, digest),
        )
    (surroundings.tmp / "input.txt").write_text("Plan the actual task")
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


def app(con: sqlite3.Connection, surroundings: AttemptSurroundings, execution: Execution) -> Attempts:
    return surroundings.attempts(
        AttemptStore(lambda: con), execution, credentials=lambda _harness: ("/bin/codex", {"SECRET": "credential"})
    )


def test_execute_and_independent_collection_preserve_facts_and_reservation(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    execution = fake(refs=("native-session",))
    result = app(con, surroundings, execution).execute(KEY, ENTRY)
    assert result.reason == "verification"
    assert result.execution is not None
    assert result.execution.answer.kind == "valid"
    assert result.execution.facts.tokens == (8, None, 3)
    assert con.execute("SELECT t_in,t_cached,t_out FROM execution").fetchone() == (8, None, 3)  # known: some count stored
    assert con.execute("SELECT session_ref FROM attempt").fetchone() == ("native-session",)
    other = fake()
    reader = app(con, surroundings, other)
    assert reader.collect(KEY) == result
    assert reader.execute(KEY, ENTRY) == result
    assert not other.calls
    harness, spec, timeout, hooks = execution.calls[0]
    assert harness.kind == "codex" and spec.argv[1] == "exec"
    assert "chosen" in spec.argv and "workspace-write" in spec.argv
    assert "--output-schema" in spec.argv
    flags = spec.argv.index("--json")
    assert spec.argv[flags - len(codex_access(CodexPolicy()).flags() + codex_access(CodexPolicy()).config()) : flags] == list(
        codex_access(CodexPolicy()).flags() + codex_access(CodexPolicy()).config()
    )
    assert spec.env == {"SECRET": "credential"} and timeout == 90
    assert isinstance(hooks, WatchedHooks) and hooks.unattended is False  # carries the live sink of the last-command time
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
        ("choices", "unavailable", "store"),
        ("input", "refused", "input"),
        ("version", "unavailable", "store"),
    ],
)
def test_invalid_admission_never_executes(tmp_path: Path, surroundings: AttemptSurroundings, change: str, status: str, reason: str) -> None:
    con = database(surroundings)
    if change == "missing":
        con.execute("DELETE FROM attempt")
    elif change == "stale":
        con.execute("UPDATE reservation SET generation=2")
    elif change == "entry":
        con.execute("UPDATE attempt SET entry_boot=NULL")
    elif change == "expired":
        con.execute("UPDATE attempt SET deadline=1")
    elif change == "choices":
        con.execute("UPDATE attempt SET model=''")
    elif change == "input":
        (tmp_path / "input.txt").write_text("Changed")
    else:
        con.execute(f"PRAGMA user_version={SCHEMA.version + 1}")
    execution = fake()
    result = app(con, surroundings, execution).execute(KEY, ENTRY)
    assert (result.status, result.reason) == (status, reason)
    assert execution.calls == []


def test_decoder_fault_leaves_captured_facts_and_can_resume_without_agent(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = database(surroundings)
    execution = fake()
    owner = app(con, surroundings, execution)

    def broken(_value: object, _rules: StepRules) -> Answer:
        raise RuntimeError("decoder bug")

    with monkeypatch.context() as patch:
        patch.setattr("taskloop.attempt.kind", lambda step: dataclasses.replace(kind(step), decode=broken))
        with pytest.raises(RuntimeError, match="decoder bug"):
            owner.execute(KEY, ENTRY)
    resumed, secrets = fake(), []
    reader = surroundings.attempts(AttemptStore(lambda: con), resumed, credentials=lambda _harness: secrets.append(1) or ("/bin/codex", {}))
    captured = reader.collect(KEY)
    assert captured.status == "pending" and captured.execution is not None and captured.execution.answer.kind == "validation_pending"
    assert captured.execution.facts.rc == 0
    assert reader.execute(KEY, ENTRY).reason == "verification"
    assert not resumed.calls and secrets == []


def test_dispatch_is_consumed_and_wrong_key_cannot_capture(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    store = AttemptStore(lambda: con)
    admitted = store.load(KEY)
    assert admitted is not None
    assert store.dispatch(admitted, BASE) == "accepted"
    assert store.dispatch(admitted, BASE) == "conflict"
    execution = fake()
    assert app(con, surroundings, execution).execute(KEY, ENTRY).status == "pending"
    assert execution.calls == []
    assert app(con, surroundings, fake()).collect(dataclasses.replace(KEY, dispatch_token="other")).status == "refused"


class Flaky:
    """Native SQLite that can go unavailable between operations, like a failing disk."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con, self.down = con, False

    def __call__(self) -> sqlite3.Connection | None:
        return None if self.down else self.con


def registered_run(run: FakeRun, flaky: Flaky, *, down_after_start: bool = False, probe: list[object] | None = None) -> Execution:
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
                probe.append(flaky.con.execute("SELECT session_ref FROM attempt").fetchone())

        return run(harness, spec, timeout, RunHooks(started=after_start, ref=observed, unattended=False))

    return call


def owner(flaky: Flaky, surroundings: AttemptSurroundings, execution: Execution, clock: Callable[[], float] = lambda: 10) -> Attempts:
    return surroundings.attempts(AttemptStore(flaky), execution, clock=clock)


def test_live_ref_is_recorded_while_running_and_duplicates_are_idempotent(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    flaky, probe = Flaky(database(surroundings)), []
    run = fake(refs=("s", "s"))
    result = owner(flaky, surroundings, registered_run(run, flaky, probe=probe)).execute(KEY, ENTRY)
    assert probe == [("s",), ("s",)]
    assert result.reason == "verification" and result.execution is not None and result.execution.session_state == "complete"


def test_absent_ref_stays_absent_and_late_reported_ref_is_recorded(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    assert app(con, surroundings, fake(refs=())).execute(KEY, ENTRY).execution is not None
    assert con.execute("SELECT session_ref FROM attempt").fetchone() == (None,)
    con2 = database(surroundings)
    late = FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), res={"ref": "late"})))
    result = app(con2, surroundings, late).execute(KEY, ENTRY)
    assert result.execution is not None and result.execution.facts.session == "late"
    assert con2.execute("SELECT session_ref FROM attempt").fetchone() == ("late",)


def test_conflicting_ref_is_recorded_not_overwritten(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    result = app(con, surroundings, fake(refs=("first", "second"))).execute(KEY, ENTRY)
    assert result.status == "conflict" and result.reason == "session"
    assert result.execution is not None and result.execution.answer.kind == "valid"
    assert con.execute("SELECT session_ref,session_conflict FROM attempt").fetchone() == ("first", 1)


def test_storage_loss_keeps_first_ref_and_conflict_then_capture_retries(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    flaky = Flaky(database(surroundings))
    execution = fake(refs=("first", "second"))
    result = owner(flaky, surroundings, registered_run(execution, flaky, down_after_start=True)).execute(KEY, ENTRY)
    assert (
        result.status == "unavailable"
        and result.pending is not None
        and flaky.con.execute("SELECT count(*) FROM execution").fetchone() == (0,)
    )
    pending = result.pending
    assert pending.sessions == SessionInput("first", True, None) and pending.facts is not None and pending.facts.rc == 0
    assert pending.evidence is not None
    flaky.down = False
    retry = owner(flaky, surroundings, fake())
    assert retry.capture(pending) == CaptureResult("accepted")
    assert retry.capture(pending) == CaptureResult("already_same")
    stored = retry.collect(KEY)
    assert stored.status == "conflict" and stored.execution is not None and stored.execution.answer.kind == "valid"
    assert flaky.con.execute("SELECT session_ref FROM attempt").fetchone() == ("first",)


def test_capture_conflicts_on_different_facts_and_a_stale_capture_cannot_rewrite(
    tmp_path: Path, surroundings: AttemptSurroundings
) -> None:
    flaky = Flaky(database(surroundings))
    result = owner(flaky, surroundings, registered_run(fake(), flaky, down_after_start=True)).execute(KEY, ENTRY)
    assert result.pending is not None
    flaky.down = False
    attempts = owner(flaky, surroundings, fake())
    assert attempts.capture(result.pending) == CaptureResult("accepted")
    assert result.pending.facts is not None
    different = dataclasses.replace(result.pending, facts=dataclasses.replace(result.pending.facts, rc=9))
    assert attempts.capture(different) == CaptureResult("conflict")
    kept = attempts.collect(KEY).execution
    assert kept is not None and kept.facts.rc == 0


def test_unavailable_storage_refuses_without_agent_and_never_reports_missing(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    flaky = Flaky(database(surroundings))
    flaky.down = True
    execution = fake()
    attempts = owner(flaky, surroundings, execution)
    assert attempts.execute(KEY, ENTRY).status == "unavailable" and attempts.collect(KEY).status == "unavailable"
    flaky.con.close()
    flaky.down = False
    assert attempts.execute(KEY, ENTRY).status == "unavailable" and execution.calls == []


def test_registration_hook_refuses_before_ref_or_result(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    now = [10.0]
    inner = fake(refs=("s",))

    def late(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        now[0] = 500.0  # the deadline passes between the launch decision and the registration
        return inner(harness, spec, timeout, hooks)

    attempts = app(con, surroundings, late)
    attempts.clock = lambda: now[0]
    result = attempts.execute(KEY, ENTRY)
    assert result.status == "refused" and result.reason == "expired"
    assert con.execute("SELECT phase,worker_pid,session_ref FROM attempt").fetchone() == ("dispatching", None, None)
    assert con.execute("SELECT count(*) FROM execution").fetchone() == (0,)


def test_reservation_change_after_dispatch_fences_registration(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)

    def swap(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        con.execute("UPDATE reservation SET generation=2")
        return fake()(harness, spec, timeout, hooks)

    assert app(con, surroundings, swap).execute(KEY, ENTRY).status == "refused"
    assert con.execute("SELECT count(*) FROM execution").fetchone() == (0,)


def test_historical_collect_needs_no_reservation_input_or_deadline(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    result = app(con, surroundings, fake()).execute(KEY, ENTRY)
    con.execute("DELETE FROM reservation")  # test-only: collection must not depend on the live reservation
    (tmp_path / "input.txt").unlink()
    con.execute("UPDATE attempt SET deadline=1")
    again = fake()
    assert app(con, surroundings, again).collect(KEY) == result and app(con, surroundings, again).execute(KEY, ENTRY) == result
    assert again.calls == []


def test_usage_unknown_is_not_zero_and_answer_grace_facts_are_kept(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    grace = FakeRun(RunOutcome(rc=-15, stop="answer", worker=WORKER, summary=Summary(text=json.dumps(PLAN), stands=True, work=True)))
    facts = app(con, surroundings, grace).execute(KEY, ENTRY).execution
    assert facts is not None and facts.facts.tokens is None and facts.facts.turns is None
    assert con.execute("SELECT t_in,t_cached,t_out,c_in,c_cached,c_out FROM execution").fetchone() == (None,) * 6  # never 0
    assert facts.facts.stop == "answer" and facts.facts.stands and facts.answer.kind == "valid"


def test_real_file_database_composition_opens_and_collects(tmp_path: Path) -> None:
    attempts = open_attempts(tmp_path / "factory.db", tmp_path, GitViews(DEFAULT_GIT_READ_SECONDS), lambda _harness: ("/bin/codex", {}))
    assert attempts.collect(KEY).status == "refused"
    assert attempts.execute(KEY, ENTRY).status == "refused"
    assert (tmp_path / "factory.db").exists()


def test_run_failure_after_registration_is_typed_and_keeps_registered_state(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)

    def crash(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert hooks is not None and hooks.started is not None
        hooks.started(WORKER)
        raise RuntimeError("library fault")

    result = app(con, surroundings, crash).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("unavailable", "run_failed:RuntimeError")
    assert con.execute("SELECT phase,worker_pid FROM attempt").fetchone() == ("registered", 42)
    assert app(con, surroundings, fake()).execute(KEY, ENTRY).status == "pending"


def test_projection_fault_keeps_evidence_and_capture_retries(
    tmp_path: Path, surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch
) -> None:
    con = database(surroundings)

    def broken(_raw: RunOutcome) -> None:
        raise RuntimeError("projection bug")

    with monkeypatch.context() as patch:
        patch.setattr("taskloop.attempt.execution_facts", broken)
        result = app(con, surroundings, fake()).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("unavailable", "projection:RuntimeError")
    assert result.pending is not None and result.pending.facts is None and result.pending.evidence is not None
    assert (tmp_path / result.pending.evidence.answer.path).exists()
    attempts = app(con, surroundings, fake())
    assert attempts.capture(result.pending) == CaptureResult("accepted")
    assert attempts.collect(KEY).reason == "verification"


def test_stored_pending_session_state_is_reconciled_by_execute(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    late = FakeRun(RunOutcome(rc=0, worker=WORKER, summary=Summary(text=json.dumps(PLAN), res={"ref": "late"})))
    assert app(con, surroundings, late).execute(KEY, ENTRY).reason == "verification"
    con.execute("UPDATE execution SET session_state='fault'")
    con.execute("UPDATE attempt SET session_ref=NULL")
    again = fake()
    result = app(con, surroundings, again).execute(KEY, ENTRY)
    assert result.reason == "verification" and again.calls == []
    assert con.execute("SELECT session_ref FROM attempt").fetchone() == ("late",)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (OSError("keychain locked"), "credentials:OSError"),
        (CredentialsUnavailable(CredentialReason.AUTH, "Local file login is missing."), "credentials:auth"),
    ],
)
def test_credentials_failure_leaves_the_attempt_admitted_and_never_dispatches(
    surroundings: AttemptSurroundings, error: Exception, reason: str
) -> None:
    con = database(surroundings)

    def refuse(_harness: HarnessKind) -> tuple[str, dict[str, str]]:
        raise error

    execution = fake()
    attempts = surroundings.attempts(AttemptStore(lambda: con), execution, credentials=refuse)
    for _ in range(2):
        result = attempts.execute(KEY, ENTRY)
        assert (result.status, result.reason) == ("unavailable", reason) and execution.calls == []
        assert con.execute("SELECT phase,rev FROM attempt").fetchone() == ("admitted", 0)


def test_files_failure_is_typed_and_leaves_the_attempt_admitted(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    (tmp_path / "attempts").write_text("a file where the artifact folder belongs")
    execution = fake()
    result = app(con, surroundings, execution).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("unavailable", "files") and execution.calls == []
    assert con.execute("SELECT phase FROM attempt").fetchone() == ("admitted",)


@pytest.mark.parametrize("me", [(8, "entry-start", "boot"), (7, "other-start", "boot"), (7, "entry-start", "other-boot")])
def test_only_the_registered_entry_executes(tmp_path: Path, surroundings: AttemptSurroundings, me: EntryIdentity) -> None:
    con, execution, asked = database(surroundings), fake(), []
    attempts = surroundings.attempts(
        AttemptStore(lambda: con), execution, credentials=lambda _harness: asked.append(1) or ("/bin/codex", {})
    )
    result = attempts.execute(KEY, me)
    assert (result.status, result.reason) == ("refused", "not_entry")
    assert asked == [] and execution.calls == [] and not (tmp_path / "attempts").exists()
    assert con.execute("SELECT phase FROM attempt").fetchone() == ("admitted",)


def test_a_selected_read_only_policy_is_launched_for_plan(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con, execution = database(surroundings), fake()
    con.execute("UPDATE attempt SET access_policy=?", ('{"harness":"codex","sandbox":"read-only"}',))
    app(con, surroundings, execution).execute(KEY, ENTRY)
    spec = execution.calls[0][1]
    assert spec.argv[spec.argv.index("-s") + 1] == "read-only"
    assert not any("sandbox_workspace_write" in flag for flag in spec.argv)


class CountingHarness(CodexHarness):
    """The real Codex harness, counting cleanups; `broken` makes `launch_spec` fail."""

    cleanups: ClassVar[list[int]] = []
    broken: ClassVar[bool] = False

    def launch_spec(self, i: LaunchInputs) -> LaunchSpec:
        if CountingHarness.broken:
            raise ValueError("bad launch")
        return super().launch_spec(i)

    def cleanup(self) -> None:
        CountingHarness.cleanups.append(1)
        super().cleanup()


@pytest.mark.parametrize(
    ("case", "status", "reason", "phase"),
    [
        ("launch", "unavailable", "launch:ValueError", "admitted"),
        ("raced", "pending", "dispatching", "admitted"),
        ("store", "unavailable", "store", "admitted"),
        ("expired", "refused", "expired", "admitted"),  # crossed while resolving the launch: never dispatched
        ("run", "pending", "verification", "captured"),
    ],
)
def test_the_harness_is_cleaned_up_once_on_every_exit(
    surroundings: AttemptSurroundings, monkeypatch: pytest.MonkeyPatch, case: str, status: str, reason: str, phase: str
) -> None:
    flaky, now, execution = Flaky(database(surroundings)), [10.0], fake()
    monkeypatch.setattr("taskloop.agents.launch.CodexHarness", CountingHarness)
    monkeypatch.setattr(CountingHarness, "cleanups", [])
    monkeypatch.setattr(CountingHarness, "broken", case == "launch")

    def credentials(_harness: HarnessKind) -> tuple[str, dict[str, str]]:
        if case == "raced":  # another writer moves the row between load and dispatch
            flaky.con.execute("UPDATE attempt SET rev=rev+1")
        flaky.down = case == "store"
        now[0] = 500.0 if case == "expired" else now[0]
        return "/bin/codex", {}

    def clock() -> float:
        return now[0]

    result = surroundings.attempts(AttemptStore(flaky), execution, credentials=credentials, clock=clock).execute(KEY, ENTRY)
    assert (result.status, result.reason) == (status, reason)
    assert CountingHarness.cleanups == [1] and len(execution.calls) == (case == "run")
    assert flaky.con.execute("SELECT phase FROM attempt").fetchone() == (phase,)


def test_the_registration_write_goes_through_the_registration_store_only(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)

    class Main(AttemptStore):
        def register(self, admission: Admission, worker: Worker) -> Literal["accepted", "already_same", "conflict"]:
            raise AssertionError("the harness registration must use the bounded registration store")

    registration_store = AttemptStore(lambda: con)
    attempts = surroundings.attempts(Main(lambda: con), fake(), registration_store=registration_store)
    assert attempts.execute(KEY, ENTRY).reason == "verification"
    assert con.execute("SELECT phase,worker_pid FROM attempt").fetchone() == ("captured", 42)


def test_the_registration_connection_is_opened_before_dispatch_and_its_fault_leaves_admitted(
    tmp_path: Path, surroundings: AttemptSurroundings
) -> None:
    con, events = database(surroundings), []

    class Main(AttemptStore):
        def dispatch(self, expected: AttemptRecord, base: str) -> Literal["accepted", "conflict"]:
            events.append("dispatch")
            return super().dispatch(expected, base)

    def opened() -> sqlite3.Connection | None:
        events.append("registration_store")
        return con

    attempts = surroundings.attempts(Main(lambda: con), fake(), registration_store=AttemptStore(opened))
    assert attempts.execute(KEY, ENTRY).reason == "verification"
    assert events[:2] == ["registration_store", "dispatch"]
    con2, run = database(surroundings), fake()
    broken = surroundings.attempts(Main(lambda: con2), run, registration_store=AttemptStore(lambda: None))
    result = broken.execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("unavailable", "store") and run.calls == []
    assert con2.execute("SELECT phase FROM attempt").fetchone() == ("admitted",)


def test_an_entry_replaced_between_load_and_dispatch_fences_the_dispatch(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con, run = database(surroundings), fake()
    store = AttemptStore(lambda: con)

    def replacing(_harness: HarnessKind) -> tuple[str, dict[str, str]]:
        assert store.register_entry(KEY, (9, "new-start", "boot"), 10, Replaced(ENTRY, "gone")) == "accepted"
        return "/bin/codex", {}

    result = surroundings.attempts(store, run, credentials=replacing).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("refused", "changed_admission") and run.calls == []
    assert con.execute("SELECT phase,entry_pid FROM attempt").fetchone() == ("admitted", 9)


def test_composition_bounds_only_the_registration_connection(tmp_path: Path) -> None:
    attempts = open_attempts(tmp_path / "factory.db", tmp_path, GitViews(DEFAULT_GIT_READ_SECONDS), lambda _harness: ("/bin/codex", {}))
    registration_store, main = attempts.registration_store.connect(), attempts.store.connect()
    assert registration_store is not None and main is not None and registration_store is not main
    assert registration_store.execute("PRAGMA busy_timeout").fetchone() == (1500,)
    assert main.execute("PRAGMA busy_timeout").fetchone() == (5000,)


def pending_result(surroundings: AttemptSurroundings) -> tuple[Flaky, Attempts, PendingResult]:
    flaky = Flaky(database(surroundings))
    result = owner(flaky, surroundings, registered_run(fake(), flaky, down_after_start=True)).execute(KEY, ENTRY)
    assert result.pending is not None and result.pending.facts is not None
    flaky.down = False
    return flaky, owner(flaky, surroundings, fake()), result.pending


def test_capture_upgrades_pending_session_state_once_and_rejects_different_evidence(
    tmp_path: Path, surroundings: AttemptSurroundings
) -> None:
    flaky, _attempts, pending = pending_result(surroundings)
    store = AttemptStore(flaky)
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
    attempts = owner(flaky, surroundings, fake())
    assert attempts.capture(dataclasses.replace(pending, evidence=other)) == CaptureResult("conflict")


def test_answer_summary_is_idempotent_and_never_replaced(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    flaky, attempts, pending = pending_result(surroundings)
    assert attempts.capture(pending) == CaptureResult("accepted")
    store = AttemptStore(flaky)
    loaded = store.load(KEY)
    assert loaded is not None and pending.evidence is not None
    same = AnswerState("valid", "planned", "commit", (P,), "Plan tl-1")
    assert store.answer(loaded.admission, pending.evidence, same) == "already_same"
    assert store.answer(loaded.admission, pending.evidence, AnswerState("missing")) == "conflict"
    assert store.answer(loaded.admission, dataclasses.replace(pending.evidence, stderr=FileRef("x", "0" * 64)), same) == "conflict"


def test_ref_callback_on_another_thread_uses_its_own_shared_writer_connection(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    store = Store(SCHEMA)
    path = tmp_path / "factory.db"
    seeded = store.open_rw(path)
    assert seeded is not None
    seed(seeded, surroundings)
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

    attempts = surroundings.attempts(AttemptStore(lambda: store.shared_rw(path), store.begin_immediate), threaded)
    assert attempts.execute(KEY, ENTRY).reason == "verification"
    assert seen and seen != [threading.get_ident()]
    assert seeded.execute("SELECT session_ref FROM attempt").fetchone() == ("threaded",)
    store.close_shared()


def test_two_connections_contend_for_one_dispatch(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    store = Store(SCHEMA)
    path = tmp_path / "factory.db"
    first = store.open_rw(path)
    assert first is not None
    seed(first, surroundings)
    record = AttemptStore(lambda: first).load(KEY)
    assert record is not None
    barrier, outcomes = threading.Barrier(2), []

    def contender() -> None:
        mine = Store(SCHEMA).open_rw(path)
        barrier.wait()
        outcomes.append(AttemptStore(lambda: mine, store.begin_immediate).dispatch(record, BASE))

    threads = [threading.Thread(target=contender) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["accepted", "conflict"]


def test_stored_pending_session_state_is_not_promoted_without_evidence(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    assert app(con, surroundings, fake()).execute(KEY, ENTRY).reason == "verification"  # the summary reports no ref: facts.session is None
    con.execute("UPDATE execution SET session_state='pending'")
    again = fake()
    attempts = app(con, surroundings, again)
    for _ in range(2):
        result = attempts.execute(KEY, ENTRY)
        assert (result.status, result.reason) == ("pending", "session_pending") and again.calls == []
    assert con.execute("SELECT session_state FROM execution").fetchone() == ("pending",)
    con.execute("UPDATE attempt SET session_ref='accepted'")
    assert attempts.execute(KEY, ENTRY).reason == "verification"
    con.execute("UPDATE execution SET session_state='fault'")
    con.execute("DELETE FROM reservation")  # a released reservation: execute on a non-terminal stored state refuses, collect still reads
    assert (attempts.execute(KEY, ENTRY).status, attempts.execute(KEY, ENTRY).reason) == ("refused", "stale_reservation")
    assert attempts.collect(KEY).reason == "session_fault"


def test_recorded_session_conflict_is_visible_without_a_result_and_blocks_complete(
    tmp_path: Path, surroundings: AttemptSurroundings
) -> None:
    flaky, attempts, pending = pending_result(surroundings)
    flaky.con.execute("UPDATE attempt SET session_ref='first',session_conflict=1")
    assert (attempts.collect(KEY).status, attempts.collect(KEY).reason) == ("conflict", "session")
    assert attempts.capture(pending).status == "accepted"
    assert flaky.con.execute("SELECT session_state FROM execution").fetchone() == ("conflict",)


def test_registration_conflict_and_same_identity_are_distinguished(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    inner = fake()

    def twice(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert hooks is not None and hooks.started is not None
        hooks.started(WORKER)
        return inner(harness, spec, timeout, hooks)  # the same identity again: already_same, not an error

    assert app(con, surroundings, twice).execute(KEY, ENTRY).reason == "verification"


def test_different_worker_identity_refuses_registration_before_exec(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)

    def different(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        assert hooks is not None and hooks.started is not None
        hooks.started(WORKER)
        hooks.started(dataclasses.replace(WORKER, pid=43))
        raise AssertionError("exec must stay gated")

    result = app(con, surroundings, different).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("conflict", "registration_conflict")


@pytest.mark.parametrize(
    ("error", "fault"),
    [(RuntimeError("bug"), "unexpected:RuntimeError"), (StoreRefused("stale_reservation"), "refused:stale_reservation")],
)
def test_ref_callback_faults_are_retained_with_cause_and_never_raised(
    tmp_path: Path, surroundings: AttemptSurroundings, error: Exception, fault: str
) -> None:
    con = database(surroundings)
    loaded = AttemptStore(lambda: con).load(KEY)
    assert loaded is not None

    class Broken(AttemptStore):
        def session(self, admission: Admission, ref: str) -> Literal["accepted", "already_same", "conflict"]:
            raise error

    latch = SessionLatch(Broken(lambda: con), loaded.admission)
    latch.observe("ref")
    assert latch.snapshot() == SessionInput("ref", False, fault)


def test_report_never_presents_pending_state_as_collected(tmp_path: Path, surroundings: AttemptSurroundings) -> None:
    result = app(database(surroundings), surroundings, fake()).execute(KEY, ENTRY)
    stored = result.execution
    assert stored is not None and report(stored).reason == "verification"
    for session_state, status, reason in (
        ("pending", "pending", "session_pending"),
        ("fault", "pending", "session_fault"),
        ("conflict", "conflict", "session"),
    ):
        shown = report(dataclasses.replace(stored, session_state=session_state))
        assert (shown.status, shown.reason) == (status, reason)
    waiting = report(dataclasses.replace(stored, answer=AnswerState("validation_pending")))
    assert (waiting.status, waiting.reason) == ("pending", "validation_pending")


def test_the_round_log_is_made_on_demand_appended_and_private(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path / "art")
    assert not (tmp_path / "art").exists()
    files.log_round("first line")
    files.log_round("second line")
    path = files.round_log()
    assert path == (tmp_path / "art").resolve() / "rounds.log"
    assert path.read_text() == "first line\nsecond line\n" and path.stat().st_mode & 0o777 == 0o600
