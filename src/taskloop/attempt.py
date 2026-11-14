"""Execute, capture, collect and verify one already admitted agent attempt; it grants no admission and releases nothing."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from time import monotonic

from any_agent import (
    DecodedAnswer,
    Harness,
    InvalidAnswer,
    LaunchSpec,
    RunHooks,
    RunOutcome,
    decode_answer,
)
from git_porcelain import Repo

from taskloop.agents.launch import AgentLaunch, LaunchFailure
from taskloop.agents.stop import AgentStops
from taskloop.agents.stop_store import StopStore
from taskloop.answer_failures import AnswerFailure, AnswerFailureData, AnswerRule
from taskloop.attempt_reads import StoreRefused, StoreUnavailable
from taskloop.attempt_result import collect, report
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import (
    Admission,
    Answer,
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
from taskloop.discussion import RefreshDiscussion
from taskloop.environment import Launch, Preparation, Renew
from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.git_views import GitProfileFiles
from taskloop.input_context import InputError, refresh
from taskloop.input_context import read as read_context
from taskloop.merge.prepare import SourcePreparation
from taskloop.prepare import Prepared
from taskloop.prepare import base as prepared_base
from taskloop.recovery.execution_models import Callback
from taskloop.resume_plan import ResumePlans
from taskloop.session import RegistrationRefused, SessionLatch, reconcile, registration_hook
from taskloop.steps import kind

type Execution = Callable[[Harness, LaunchSpec, float, RunHooks | None], RunOutcome]
ACCEPTED = ("accepted", "already_same")


class Attempts:
    def __init__(
        self,
        store: AttemptStore,
        files: EvidenceFiles,
        agent: AgentLaunch,
        execution: Execution,
        clock: Callable[[], float],
        checkouts: Checkouts,
        slot_files: SlotFiles,
        registration_store: AttemptStore | None = None,
        environment: Preparation | None = None,
        source_preparation: SourcePreparation | None = None,
        monotonic: Callable[[], float] = monotonic,
        discussion: RefreshDiscussion | None = None,
    ) -> None:
        """`registration_store` serves only the harness registration write (composition bounds its busy wait); default `store`.
        `slot_files` is the plain-read port the slot pointer check uses before any Git call on the slot. `environment`
        prepares the slot of a step kind with `environment` (implement); without it such a step is refused, never run
        without its setup."""
        self.store, self.files, self.agent = store, files, agent
        self.execution, self.clock, self.checkouts, self.slot_files = execution, clock, checkouts, slot_files
        self.registration_store = store if registration_store is None else registration_store
        self.environment = environment
        self.source_preparation = source_preparation
        self.monotonic = monotonic
        self.discussion = discussion

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

    def capture(self, pending: PendingResult, callback: Callback | None = None) -> CaptureResult:
        """Retry the unfinished DB capture of returned facts; never runs the agent."""
        result, pending = self._capture(pending, callback)
        if result.status in ACCEPTED:
            # on failure the captured facts stay validation_pending; a later execute finishes the phase without the agent
            with suppress(StoreUnavailable, StoreRefused):
                self._validate(pending.admission, pending.evidence, pending.raw.summary.text, callback)
        return result

    def _resume(self, key: AttemptKey, stored: StoredExecution) -> AttemptResult:
        if stored.answer.kind != "validation_pending" and stored.session_state in ("complete", "conflict"):
            return report(stored)
        record = self.store.load(key)
        if record is None:
            return AttemptResult("refused", "absent")
        callback = self.store.callback(key)
        if stored.session_state in ("pending", "fault"):
            stored = self._refresh(record, stored, callback)
        if stored.answer.kind != "validation_pending":
            return report(stored)
        try:
            text = self.files.read(stored.evidence.answer)
        except EvidenceError:
            return AttemptResult("unavailable", "evidence", stored)
        return self._answered(record.admission, stored.evidence, text, callback)

    def _refresh(self, record: AttemptRecord, stored: StoredExecution, callback: Callback | None = None) -> StoredExecution:
        """Upgrade a stored pending/fault session state only on evidence: a recorded conflict, a reported session that is
        now recorded, or a session already accepted on the attempt. Otherwise it stays as it was."""
        if record.session_conflict:
            session_state = "conflict"
        elif stored.facts.session is not None:
            session_state = reconcile(self.store, record.admission, SessionInput(), stored.facts, callback)
        elif record.session_ref is not None:
            session_state = "complete"
        else:
            return stored
        self.store.capture(record.admission, None, stored.facts, stored.evidence, session_state, callback)
        return self.store.collect(record.admission.key) or stored

    def _refusal(self, admission: Admission, me: EntryIdentity, now: float) -> str | None:
        if admission.entry != me:
            return "not_entry"
        if now >= admission.deadline:
            return "expired"
        return None

    def _start(self, record: AttemptRecord, me: EntryIdentity, renew: Renew | None) -> AttemptResult:
        """Credentials, files, the launch spec, then the slot's preparation onto its task branch and the base check
        (`prepare.base`) and, for a kind with `environment`, the slot's environment (`environment.Preparation`) resolve
        before dispatch: their failure leaves the attempt `admitted`. The slot HEAD read there is B, recorded by the
        dispatch write."""
        admission = record.admission
        now, started = self.clock(), self.monotonic()
        refusal = self._refusal(admission, me, now)
        if refusal is not None:
            return AttemptResult("refused", refusal)

        def runtime_clock() -> float:
            return now + (self.monotonic() - started)

        try:
            prompt = self.files.read(admission.input_ref)
        except EvidenceError:
            return AttemptResult("refused", "input")
        launch = self._launch(admission, prompt)
        if isinstance(launch, AttemptResult):
            return launch
        harness, spec, credentials, probe = launch
        running = False
        try:
            base = self._prepared(record, renew, credentials, probe)
            if isinstance(base, AttemptResult):
                return base
            spec = self._context(admission, base, spec)
            if isinstance(spec, AttemptResult):
                return spec
            running = True
            return self._dispatch(record, base, harness, spec, runtime_clock)
        finally:
            if not running:
                harness.cleanup()

    def _dispatch(
        self, record: AttemptRecord, base: Prepared, harness: Harness, spec: LaunchSpec, runtime_clock: Callable[[], float]
    ) -> AttemptResult:
        running = False
        try:
            self.registration_store.warm()
            if self.store.dispatch(record, base.head) == "conflict":
                return AttemptResult("pending", "dispatching")
            running = True
            return self._run(record.admission, harness, spec, runtime_clock)
        finally:
            if not running:
                harness.cleanup()

    def _context(self, admission: Admission, base: Prepared, spec: LaunchSpec) -> LaunchSpec | AttemptResult:
        try:
            path = Path(admission.slot_path)
            def pinned(root: Path, /, *, git_dir: Path | None = None) -> Repo:
                return self.checkouts(root, git_dir=base.gitdir)
            context = read_context(GitProfileFiles(path, pinned), base.head)
            spec = replace(spec, stdin=refresh(spec.stdin, context))
            self.files.put_launched_input(admission.key, spec.stdin)
            return spec
        except (InputError, EvidenceError, OSError) as error:
            return AttemptResult("refused", "input", explanation=str(error))

    def _prepared(
        self, record: AttemptRecord, renew: Renew | None, credentials: Launch, probe: tuple[str, ...] | None
    ) -> Prepared | AttemptResult:
        """The slot on its branch (`prepare.base`), then, for a kind with `environment`, its setup sequence with the
        credentials' executable and scrubbed environment."""
        validation = ResumePlans(self.store, self.checkouts)
        if validation.required(record):
            original = prepared_base(self.checkouts, self.slot_files, record, self.clock)
            if isinstance(original, AttemptResult):
                return original
            refused = validation.entry(record, original, self.discussion)
            if refused is not None:
                return refused
        base = (prepared_base(self.checkouts, self.slot_files, record, self.clock) if self.source_preparation is None else
                self.source_preparation.prepare(record, renew, credentials, probe))
        if isinstance(base, AttemptResult) or not kind(record.admission.step).environment:
            return base
        refused = validation.entry(record, base, self.discussion)
        if refused is not None:
            return refused
        if self.environment is None or renew is None:
            return AttemptResult("unavailable", "environment:unwired")
        return self.environment.prepare(record, base, renew, credentials, probe) or base

    def _launch(self, admission: Admission, prompt: str) -> tuple[Harness, LaunchSpec, Launch, tuple[str, ...] | None] | AttemptResult:
        try:
            schema, out_file = self.files.prepare(admission.key, kind(admission.step).answer_schema)
            root = self.files.launch_root(admission.key)
        except (EvidenceError, OSError):
            return AttemptResult("unavailable", "files")
        launch = self.agent.build(admission.setting, Path(admission.slot_path), kind(admission.step).environment,
                                  root, schema, out_file, prompt)
        if isinstance(launch, LaunchFailure):
            return AttemptResult("unavailable", launch.reason, explanation=launch.explanation)
        return launch.harness, launch.spec, launch.credentials, launch.probe

    def _run(
        self, admission: Admission, harness: Harness, spec: LaunchSpec, runtime_clock: Callable[[], float]
    ) -> AttemptResult:
        remaining = admission.deadline - runtime_clock()
        if remaining <= 0:
            harness.cleanup()
            return AttemptResult("refused", "expired")
        called = self._call(admission, harness, spec, remaining, runtime_clock)
        if isinstance(called, AttemptResult):
            return called
        raw, sessions = called
        result, pending = self._capture(PendingResult(admission, raw, None, sessions))
        if result.status in ACCEPTED:
            return self._answered(admission, pending.evidence, raw.summary.text)
        return AttemptResult("conflict" if result.status == "conflict" else "unavailable", result.reason, pending=pending)

    def _call(
        self, admission: Admission, harness: Harness, spec: LaunchSpec, remaining: float, runtime_clock: Callable[[], float]
    ) -> tuple[RunOutcome, SessionInput] | AttemptResult:
        latch = SessionLatch(self.store, admission)
        stops = AgentStops(StopStore(self.registration_store.connect, self.registration_store.begin), admission, self.clock)
        hooks = WatchedHooks(
            started=registration_hook(self.registration_store, admission, runtime_clock), ref=latch.observe, unattended=False,
            before_stop=stops.before, after_stop=stops.after, live=CommandSink(self.files, admission.key, self.clock),
        )
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

    def _capture(self, pending: PendingResult, callback: Callback | None = None) -> tuple[CaptureResult, PendingResult]:
        """Capture evidence files, then facts with answer=validation_pending, before any answer decoding."""
        admission, evidence = pending.admission, pending.evidence
        if evidence is None:
            try:
                evidence = (self.files.capture(admission.key, pending.raw) if callback is None
                            else self.files.capture(admission.key, pending.raw, callback))
            except EvidenceError:
                return CaptureResult("unavailable", "evidence"), pending
            pending = replace(pending, evidence=evidence)
        if callback is not None and evidence != self.files.capture_refs(admission.key, pending.raw, callback):
            return CaptureResult("conflict", "evidence"), pending
        try:
            facts = pending.facts or execution_facts(pending.raw)
        except Exception as error:  # a projection fault must not lose the returned outcome: its evidence is already written
            return CaptureResult("unavailable", "projection:" + type(error).__name__), pending
        pending = replace(pending, facts=facts)
        session_state = reconcile(self.store, admission, pending.sessions, facts, callback)
        try:
            status = self.store.capture(admission, pending.raw.worker, facts, evidence, session_state, callback)
        except StoreUnavailable:
            return CaptureResult("unavailable", "store"), pending
        except StoreRefused as error:
            return CaptureResult("conflict", str(error)), pending
        return CaptureResult(status), pending

    def _answered(self, admission: Admission, evidence: Evidence | None, text: str, callback: Callback | None = None) -> AttemptResult:
        if self._validate(admission, evidence, text, callback) == "conflict":
            return AttemptResult("conflict", "answer")
        stored = self.store.collect(admission.key)
        return AttemptResult("unavailable", "collect") if stored is None else report(stored)

    def _validate(self, admission: Admission, evidence: Evidence | None, text: str, callback: Callback | None = None) -> str:
        """The released strict decoder plus the step kind's pure decoder; decoder faults propagate."""
        if evidence is None:
            return "conflict"
        step = kind(admission.step)
        rules = step.rules(admission.task.task_id)

        def validate(value: object) -> Answer | AnswerFailure:
            try:
                return step.decode(value, rules)
            except AnswerFailure as failure:
                return failure

        answer = decode_answer(text, validate)
        if isinstance(answer, DecodedAnswer):
            value = answer.value
            if isinstance(value, AnswerFailure):
                state = AnswerState("schema_invalid", failure=value.data)
            else:
                state = AnswerState("valid", value.disposition, value.effect, value.paths, value.message)
        elif isinstance(answer, InvalidAnswer):
            if answer.kind != "json":
                raise ValueError("Unexpected answer decoder failure: " + answer.reason)
            failure = AnswerFailureData(rule=AnswerRule.JSON, explanation="Answer must be one complete strict JSON value: " + answer.reason)
            state = AnswerState("json_invalid", failure=failure)
        else:
            state = AnswerState("missing", failure=AnswerFailureData(rule=AnswerRule.MISSING, explanation="Answer must not be empty"))
        return self.store.answer(admission, evidence, state, callback)
