"""Execute, publish and collect one already admitted plan attempt; it grants no admission and releases nothing."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from typing import Final, Literal

from any_agent import CodexHarness, DecodedAnswer, Harness, InvalidAnswer, LaunchInputs, LaunchSpec, RunHooks, RunOutcome, decode_answer

from taskloop.plan_files import EvidenceError, PlanFiles
from taskloop.plan_session import GateRefused, SessionLatch, reconcile, registration_gate
from taskloop.plan_store import PlanStore, StoreRefused, StoreUnavailable
from taskloop.plan_types import (
    Admission,
    AnswerState,
    AttemptKey,
    AttemptRecord,
    AttemptResult,
    Evidence,
    PendingPlanResult,
    PlanDecoder,
    PublicationResult,
    SessionInput,
    StoredExecution,
    decode_plan_answer,
    execution_facts,
)

type Execution = Callable[[Harness, LaunchSpec, float, RunHooks | None], RunOutcome]
type Credentials = Callable[[], tuple[str, dict[str, str]]]
ACCEPTED = ("accepted", "already_same")
SANDBOX = "workspace-write"  # the only mode CODEX_ACCESS constrains
# Baseline `decide.py` CODEX_ACCESS (731b7c76), verbatim: neither the user's config nor a repo file widens or narrows these.
# The sandbox has no network and writes only the working directory; a command it blocks may ask to run outside it, and
# Codex's automatic reviewer (a model, no human) approves or refuses that one command (accepted by codex-cli 0.162.1).
CODEX_ACCESS: Final = (
    "--ignore-user-config",
    "--ignore-rules",
    "-c",
    "sandbox_workspace_write.network_access=false",
    "-c",
    "sandbox_workspace_write.writable_roots=[]",
    "-c",
    "approval_policy=on-request",
    "-c",
    "approvals_reviewer=auto_review",
    "-c",
    "tool_output_token_limit=3000",
)


class CredentialsUnavailable(Exception):
    """The credential source has no usable login, executable or environment; `reason` is one fixed word."""

    def __init__(self, reason: Literal["path", "codex", "home", "auth", "git_config"]) -> None:
        super().__init__(reason)
        self.reason = reason


def report(stored: StoredExecution) -> AttemptResult:
    """Stored terminal data is collected; a pending validation or session publication is never reported as complete."""
    if stored.answer.kind == "validation_pending":
        return AttemptResult("pending", "validation_pending", stored)
    if stored.publication == "conflict":
        return AttemptResult("conflict", "session", stored)
    if stored.publication != "complete":
        return AttemptResult("pending", "session_" + stored.publication, stored)
    return AttemptResult("collected", execution=stored)


class PlanAttempts:
    def __init__(
        self,
        store: PlanStore,
        files: PlanFiles,
        credentials: Credentials,
        execution: Execution,
        clock: Callable[[], float],
        decoder: PlanDecoder = decode_plan_answer,
        gate: PlanStore | None = None,
    ) -> None:
        """`gate` serves only the harness registration write (composition bounds its busy wait); default `store`."""
        self.store, self.files, self.credentials = store, files, credentials
        self.execution, self.clock, self.decoder = execution, clock, decoder
        self.gate = store if gate is None else gate

    def collect(self, key: AttemptKey) -> AttemptResult:
        """Read-only: stored facts need no reservation, input, credential or remaining deadline."""
        try:
            stored = self.store.collect(key)
            if stored is not None:
                return report(stored)
            state = self.store.state(key)
        except StoreUnavailable:
            return AttemptResult("unavailable", "collect")
        if state is None:
            return AttemptResult("refused", "absent")
        return AttemptResult("conflict", "session") if state[1] else AttemptResult("pending", state[0])

    def execute(self, key: AttemptKey, me: tuple[int, str, str]) -> AttemptResult:
        """`me` is the caller's own (pid, start, boot): an admitted attempt dispatches only for its registered entry."""
        try:
            stored = self.store.collect(key)
            if stored is not None:
                return self._resume(key, stored)
            record = self.store.load(key)
            if record is None:
                return AttemptResult("refused", "absent")
            if record.phase != "admitted":
                return AttemptResult("pending", record.phase)
            return self._start(record, me)
        except StoreUnavailable:
            return AttemptResult("unavailable", "store")
        except StoreRefused as error:
            return AttemptResult("refused", str(error))

    def publish(self, pending: PendingPlanResult) -> PublicationResult:
        """Retry the unfinished DB publication of returned facts; never runs the agent."""
        result, pending = self._publish(pending)
        if result.status in ACCEPTED:
            # on failure the captured facts stay validation_pending; a later execute finishes the phase without the agent
            with suppress(StoreUnavailable, StoreRefused):
                self._validate(pending.admission, pending.evidence, pending.raw.summary.text)
        return result

    def _resume(self, key: AttemptKey, stored: StoredExecution) -> AttemptResult:
        if stored.answer.kind != "validation_pending" and stored.publication in ("complete", "conflict"):
            return report(stored)
        record = self.store.load(key)
        if record is None:
            return AttemptResult("refused", "absent")
        if stored.publication in ("pending", "fault"):
            stored = self._refresh(record, stored)
        if stored.answer.kind != "validation_pending":
            return report(stored)
        try:
            text = self.files.read(stored.evidence.answer)
        except EvidenceError:
            return AttemptResult("unavailable", "evidence", stored)
        return self._answered(record.admission, stored.evidence, text)

    def _refresh(self, record: AttemptRecord, stored: StoredExecution) -> StoredExecution:
        """Upgrade a stored pending/fault publication only on evidence: a recorded conflict, a reported session that now
        publishes, or a session already accepted on the attempt. Otherwise it stays as it was."""
        if record.session_conflict:
            publication = "conflict"
        elif stored.facts.session is not None:
            publication = reconcile(self.store, record.admission, SessionInput(), stored.facts)
        elif record.session_ref is not None:
            publication = "complete"
        else:
            return stored
        self.store.capture(record.admission, None, stored.facts, stored.evidence, publication)
        return self.store.collect(record.admission.key) or stored

    def _refusal(self, admission: Admission, me: tuple[int, str, str]) -> str | None:
        if admission.entry != me:
            return "not_entry"
        if self.clock() >= admission.deadline:
            return "expired"
        if not all(value.strip() for value in (admission.model, admission.effort, admission.sandbox)):
            return "choices"
        return "sandbox" if admission.sandbox != SANDBOX else None

    def _start(self, record: AttemptRecord, me: tuple[int, str, str]) -> AttemptResult:
        """Credentials, files and the launch spec resolve before dispatch: their failure leaves the attempt `admitted`."""
        admission = record.admission
        refusal = self._refusal(admission, me)
        if refusal is not None:
            return AttemptResult("refused", refusal)
        try:
            prompt = self.files.read(admission.input_ref)
        except EvidenceError:
            return AttemptResult("refused", "input")
        launch = self._launch(admission, prompt)
        if isinstance(launch, AttemptResult):
            return launch
        harness, spec = launch
        running = False
        try:
            if self.clock() >= admission.deadline:  # crossed while resolving the launch: stays admitted
                return AttemptResult("refused", "expired")
            self.gate.warm()  # the first gated open runs here, never inside the harness registration window
            if self.store.dispatch(record) == "conflict":
                return AttemptResult("pending", "dispatching")
            running = True
            return self._run(admission, harness, spec)
        finally:
            if not running:
                harness.cleanup()

    def _launch(self, admission: Admission, prompt: str) -> tuple[CodexHarness, LaunchSpec] | AttemptResult:
        try:
            exe, env = self.credentials()
        except CredentialsUnavailable as error:
            return AttemptResult("unavailable", "credentials:" + error.reason)
        except Exception as error:  # the credential source is injected; its failure is typed, with its cause visible
            return AttemptResult("unavailable", "credentials:" + type(error).__name__)
        try:
            schema, out_file = self.files.prepare(admission.key, admission.plan_path)
        except EvidenceError:
            return AttemptResult("unavailable", "files")
        harness = CodexHarness()
        inputs = LaunchInputs(
            exe=exe,
            cwd=admission.cwd,
            model=admission.model,
            effort=admission.effort,
            prompt=prompt,
            env=env,
            schema=schema,
            sandbox=admission.sandbox,
            out_file=out_file,
            access=list(CODEX_ACCESS),
        )
        try:
            return harness, harness.launch_spec(inputs)
        except Exception as error:
            harness.cleanup()
            return AttemptResult("unavailable", "launch:" + type(error).__name__)

    def _run(self, admission: Admission, harness: CodexHarness, spec: LaunchSpec) -> AttemptResult:
        remaining = admission.deadline - self.clock()
        if remaining <= 0:
            harness.cleanup()
            return AttemptResult("refused", "expired")
        called = self._call(admission, harness, spec, remaining)
        if isinstance(called, AttemptResult):
            return called
        raw, sessions = called
        result, pending = self._publish(PendingPlanResult(admission, raw, None, sessions))
        if result.status in ACCEPTED:
            return self._answered(admission, pending.evidence, raw.summary.text)
        return AttemptResult("conflict" if result.status == "conflict" else "unavailable", result.reason, pending=pending)

    def _call(
        self, admission: Admission, harness: CodexHarness, spec: LaunchSpec, remaining: float
    ) -> tuple[RunOutcome, SessionInput] | AttemptResult:
        latch = SessionLatch(self.store, admission)
        hooks = RunHooks(started=registration_gate(self.gate, admission, self.clock), ref=latch.observe, unattended=False)
        try:
            return self.execution(harness, spec, remaining, hooks), latch.snapshot()
        except GateRefused as error:
            return AttemptResult("conflict" if str(error) == "registration_conflict" else "refused", str(error))
        except StoreRefused as error:
            return AttemptResult("refused", str(error))
        except StoreUnavailable:
            return AttemptResult("unavailable", "register")
        except Exception as error:  # registered worker and phase stay in the DB; nothing is erased or retried here
            return AttemptResult("unavailable", "run_failed:" + type(error).__name__)
        finally:
            harness.cleanup()

    def _publish(self, pending: PendingPlanResult) -> tuple[PublicationResult, PendingPlanResult]:
        """Capture evidence files, then facts with answer=validation_pending, before any answer decoding."""
        admission, evidence = pending.admission, pending.evidence
        if evidence is None:
            try:
                evidence = self.files.capture(admission.key, pending.raw)
            except EvidenceError:
                return PublicationResult("unavailable", "evidence"), pending
            pending = replace(pending, evidence=evidence)
        try:
            facts = pending.facts or execution_facts(pending.raw)
        except Exception as error:  # a projection fault must not lose the returned outcome: its evidence is already written
            return PublicationResult("unavailable", "projection:" + type(error).__name__), pending
        pending = replace(pending, facts=facts)
        publication = reconcile(self.store, admission, pending.sessions, facts)
        try:
            status = self.store.capture(admission, pending.raw.worker, facts, evidence, publication)
        except StoreUnavailable:
            return PublicationResult("unavailable", "store"), pending
        except StoreRefused as error:
            return PublicationResult("conflict", str(error)), pending
        return PublicationResult(status), pending

    def _answered(self, admission: Admission, evidence: Evidence | None, text: str) -> AttemptResult:
        if self._validate(admission, evidence, text) == "conflict":
            return AttemptResult("conflict", "answer")
        stored = self.store.collect(admission.key)
        return AttemptResult("unavailable", "collect") if stored is None else report(stored)

    def _validate(self, admission: Admission, evidence: Evidence | None, text: str) -> str:
        """The released strict decoder plus the factory's pure PlanAnswer decoder; decoder faults propagate."""
        if evidence is None:
            return "conflict"
        answer = decode_answer(text, lambda value: self.decoder(value, admission.plan_path))
        if isinstance(answer, DecodedAnswer):
            state = AnswerState("valid", answer.value.disposition, answer.value.plan_path, answer.value.commit)
        elif isinstance(answer, InvalidAnswer):
            state = AnswerState("json_invalid" if answer.kind == "json" else "schema_invalid")
        else:
            state = AnswerState("missing")
        return self.store.answer(admission, evidence, state)
