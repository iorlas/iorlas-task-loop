"""Execute, capture, collect and verify one already admitted plan attempt; it grants no admission and releases nothing."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Literal

from any_agent import (
    CodexHarness,
    DecodedAnswer,
    Harness,
    InvalidAnswer,
    LaunchInputs,
    LaunchSpec,
    RunHooks,
    RunOutcome,
    decode_answer,
)

from taskloop.access import CODEX_ACCESS, SANDBOX, folders, prepared_access
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_result import collect, report
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import (
    Admission,
    AnswerState,
    AttemptKey,
    AttemptRecord,
    AttemptResult,
    CaptureResult,
    Checkouts,
    EntryIdentity,
    Evidence,
    PendingResult,
    SessionInput,
    SlotFiles,
    StoredExecution,
    execution_facts,
)
from taskloop.command_sink import CommandSink, WatchedHooks
from taskloop.environment import Launch, Preparation, Renew
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.harness_choice import launchable
from taskloop.prepare import Prepared
from taskloop.prepare import base as prepared_base
from taskloop.session import RegistrationRefused, SessionLatch, reconcile, registration_hook
from taskloop.steps import kind

type Execution = Callable[[Harness, LaunchSpec, float, RunHooks | None], RunOutcome]
type Credentials = Callable[[], tuple[str, dict[str, str]]]
ACCEPTED = ("accepted", "already_same")


class CredentialsUnavailable(Exception):
    """The credential source has no usable login, executable or environment; `reason` is one fixed word."""

    def __init__(self, reason: Literal["path", "codex", "home", "auth"]) -> None:
        super().__init__(reason)
        self.reason = reason


class Attempts:
    def __init__(
        self,
        store: AttemptStore,
        files: EvidenceFiles,
        credentials: Credentials,
        execution: Execution,
        clock: Callable[[], float],
        checkouts: Checkouts,
        slot_files: SlotFiles,
        registration_store: AttemptStore | None = None,
        environment: Preparation | None = None,
    ) -> None:
        """`registration_store` serves only the harness registration write (composition bounds its busy wait); default `store`.
        `slot_files` is the plain-read port the slot pointer check uses before any Git call on the slot. `environment`
        prepares the slot of a step kind with `environment` (implement); without it such a step is refused, never run
        without its setup."""
        self.store, self.files, self.credentials = store, files, credentials
        self.execution, self.clock, self.checkouts, self.slot_files = execution, clock, checkouts, slot_files
        self.registration_store = store if registration_store is None else registration_store
        self.environment = environment

    def collect(self, key: AttemptKey) -> AttemptResult:
        return collect(self.store, key)

    def execute(self, key: AttemptKey, me: EntryIdentity, renew: Renew | None = None) -> AttemptResult:
        """`me` is the caller's own (pid, start, boot): an admitted attempt dispatches only for its registered entry.
        `renew` renews the tracker claim once after a step's environment is prepared (the entry's keep-alive)."""
        try:
            stored = self.store.collect(key)
            if stored is not None:
                return self._resume(key, stored)
            record = self.store.load(key)
            if record is None:
                return AttemptResult("refused", "absent")
            if record.phase != "admitted":
                return AttemptResult("pending", record.phase)
            return self._start(record, me, renew)
        except StoreUnavailable:
            return AttemptResult("unavailable", "store")
        except StoreRefused as error:
            return AttemptResult("refused", str(error))

    def capture(self, pending: PendingResult) -> CaptureResult:
        """Retry the unfinished DB capture of returned facts; never runs the agent."""
        result, pending = self._capture(pending)
        if result.status in ACCEPTED:
            # on failure the captured facts stay validation_pending; a later execute finishes the phase without the agent
            with suppress(StoreUnavailable, StoreRefused):
                self._validate(pending.admission, pending.evidence, pending.raw.summary.text)
        return result

    def _resume(self, key: AttemptKey, stored: StoredExecution) -> AttemptResult:
        if stored.answer.kind != "validation_pending" and stored.session_state in ("complete", "conflict"):
            return report(stored)
        record = self.store.load(key)
        if record is None:
            return AttemptResult("refused", "absent")
        if stored.session_state in ("pending", "fault"):
            stored = self._refresh(record, stored)
        if stored.answer.kind != "validation_pending":
            return report(stored)
        try:
            text = self.files.read(stored.evidence.answer)
        except EvidenceError:
            return AttemptResult("unavailable", "evidence", stored)
        return self._answered(record.admission, stored.evidence, text)

    def _refresh(self, record: AttemptRecord, stored: StoredExecution) -> StoredExecution:
        """Upgrade a stored pending/fault session state only on evidence: a recorded conflict, a reported session that is
        now recorded, or a session already accepted on the attempt. Otherwise it stays as it was."""
        if record.session_conflict:
            session_state = "conflict"
        elif stored.facts.session is not None:
            session_state = reconcile(self.store, record.admission, SessionInput(), stored.facts)
        elif record.session_ref is not None:
            session_state = "complete"
        else:
            return stored
        self.store.capture(record.admission, None, stored.facts, stored.evidence, session_state)
        return self.store.collect(record.admission.key) or stored

    def _refusal(self, admission: Admission, me: EntryIdentity) -> str | None:
        if admission.entry != me:
            return "not_entry"
        if self.clock() >= admission.deadline:
            return "expired"
        if not all(value.strip() for value in (admission.model, admission.effort, admission.sandbox)):
            return "choices"
        return "sandbox" if admission.sandbox != SANDBOX else None

    def _start(self, record: AttemptRecord, me: EntryIdentity, renew: Renew | None) -> AttemptResult:
        """Credentials, files, the launch spec, then the slot's preparation onto its task branch and the base check
        (`prepare.base`) and, for a kind with `environment`, the slot's environment (`environment.Preparation`) resolve
        before dispatch: their failure leaves the attempt `admitted`. The slot HEAD read there is B, recorded by the
        dispatch write."""
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
        harness, spec, credentials = launch
        running = False
        try:
            base = self._prepared(record, renew, credentials)
            if isinstance(base, AttemptResult):
                return base
            self.registration_store.warm()  # the first registration open runs here, never inside the harness registration window
            if self.store.dispatch(record, base.head) == "conflict":
                return AttemptResult("pending", "dispatching")
            running = True
            return self._run(admission, harness, spec)
        finally:
            if not running:
                harness.cleanup()

    def _prepared(self, record: AttemptRecord, renew: Renew | None, credentials: Launch) -> Prepared | AttemptResult:
        """The slot on its branch (`prepare.base`), then, for a kind with `environment`, its setup sequence with the
        credentials' executable and scrubbed environment."""
        base = prepared_base(self.checkouts, self.slot_files, record, self.clock)
        if isinstance(base, AttemptResult) or not kind(record.admission.step).environment:
            return base
        if self.environment is None or renew is None:
            return AttemptResult("unavailable", "environment:unwired")
        return self.environment.prepare(record, base, renew, credentials) or base

    def _launch(self, admission: Admission, prompt: str) -> tuple[CodexHarness, LaunchSpec, Launch] | AttemptResult:
        """The launch spec: plan's access unchanged; a kind with `environment` writes its three folders too, and its shell
        (only) gets its tools pointed there and uv offline (`access.prepared_access`). Codex's own environment is the
        credentials' for both. They come back for setup."""
        try:
            exe, env = self.credentials()
        except CredentialsUnavailable as error:
            return AttemptResult("unavailable", "credentials:" + error.reason)
        except Exception as error:  # the credential source is injected; its failure is typed, with its cause visible
            return AttemptResult("unavailable", "credentials:" + type(error).__name__)
        try:
            schema, out_file = self.files.prepare(admission.key, kind(admission.step).answer_schema)
        except EvidenceError:
            return AttemptResult("unavailable", "files")
        harness = launchable(admission.harness)
        if harness is None:  # the credentials are the machine's Codex login: no other harness has any yet
            return AttemptResult("unavailable", "harness:" + admission.harness)
        access = prepared_access(folders(Path(admission.slot_path))) if kind(admission.step).environment else CODEX_ACCESS
        inputs = LaunchInputs(
            exe=exe,
            cwd=admission.slot_path,
            model=admission.model,
            effort=admission.effort,
            prompt=prompt,
            env=env,
            schema=schema,
            sandbox=admission.sandbox,
            out_file=out_file,
            access=list(access),
        )
        try:
            return harness, harness.launch_spec(inputs), (exe, env)
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
        result, pending = self._capture(PendingResult(admission, raw, None, sessions))
        if result.status in ACCEPTED:
            return self._answered(admission, pending.evidence, raw.summary.text)
        return AttemptResult("conflict" if result.status == "conflict" else "unavailable", result.reason, pending=pending)

    def _call(
        self, admission: Admission, harness: CodexHarness, spec: LaunchSpec, remaining: float
    ) -> tuple[RunOutcome, SessionInput] | AttemptResult:
        latch = SessionLatch(self.store, admission)
        hooks = WatchedHooks(started=registration_hook(self.registration_store, admission, self.clock), ref=latch.observe, unattended=False,
                             live=CommandSink(self.files, admission.key, self.clock))
        try:
            return self.execution(harness, spec, remaining, hooks), latch.snapshot()
        except RegistrationRefused as error:
            return AttemptResult("conflict" if error.reason == "registration_conflict" else "refused", error.reason)
        except StoreRefused as error:
            return AttemptResult("refused", str(error))
        except StoreUnavailable:
            return AttemptResult("unavailable", "register")
        except Exception as error:  # registered worker and phase stay in the DB; nothing is erased or retried here
            return AttemptResult("unavailable", "run_failed:" + type(error).__name__)
        finally:
            harness.cleanup()

    def _capture(self, pending: PendingResult) -> tuple[CaptureResult, PendingResult]:
        """Capture evidence files, then facts with answer=validation_pending, before any answer decoding."""
        admission, evidence = pending.admission, pending.evidence
        if evidence is None:
            try:
                evidence = self.files.capture(admission.key, pending.raw)
            except EvidenceError:
                return CaptureResult("unavailable", "evidence"), pending
            pending = replace(pending, evidence=evidence)
        try:
            facts = pending.facts or execution_facts(pending.raw)
        except Exception as error:  # a projection fault must not lose the returned outcome: its evidence is already written
            return CaptureResult("unavailable", "projection:" + type(error).__name__), pending
        pending = replace(pending, facts=facts)
        session_state = reconcile(self.store, admission, pending.sessions, facts)
        try:
            status = self.store.capture(admission, pending.raw.worker, facts, evidence, session_state)
        except StoreUnavailable:
            return CaptureResult("unavailable", "store"), pending
        except StoreRefused as error:
            return CaptureResult("conflict", str(error)), pending
        return CaptureResult(status), pending

    def _answered(self, admission: Admission, evidence: Evidence | None, text: str) -> AttemptResult:
        if self._validate(admission, evidence, text) == "conflict":
            return AttemptResult("conflict", "answer")
        stored = self.store.collect(admission.key)
        return AttemptResult("unavailable", "collect") if stored is None else report(stored)

    def _validate(self, admission: Admission, evidence: Evidence | None, text: str) -> str:
        """The released strict decoder plus the step kind's pure decoder; decoder faults propagate."""
        if evidence is None:
            return "conflict"
        step = kind(admission.step)
        rules = step.rules(admission.task.task_id)
        answer = decode_answer(text, lambda value: step.decode(value, rules))
        if isinstance(answer, DecodedAnswer):
            value = answer.value
            state = AnswerState("valid", value.disposition, value.effect, value.paths, value.message)
        elif isinstance(answer, InvalidAnswer):
            state = AnswerState("json_invalid" if answer.kind == "json" else "schema_invalid")
        else:
            state = AnswerState("missing")
        return self.store.answer(admission, evidence, state)
