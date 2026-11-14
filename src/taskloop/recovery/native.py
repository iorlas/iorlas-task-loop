"""Native saved-session execution with registration preceding all session/result callbacks."""

from pathlib import Path

from any_agent import Harness, LaunchSpec
from any_agent.procs import Worker

from taskloop.agents.launch import LaunchFailure
from taskloop.agents.stop import AgentStops
from taskloop.agents.stop_store import StopStore
from taskloop.attempt import Attempts
from taskloop.attempt_reads import StoreUnavailable
from taskloop.attempt_types import Admission
from taskloop.command_sink import CommandSink, WatchedHooks
from taskloop.drain.models import Identity
from taskloop.evidence_files import EvidenceError
from taskloop.recovery.callbacks import Callbacks, PendingExecution
from taskloop.recovery.models import Intent, Outcome, Result
from taskloop.recovery.state_store import callback
from taskloop.recovery.store import RecoveryStore
from taskloop.session import RegistrationRefused
from taskloop.steps import kind


class NativeContinuation:
    def __init__(self, attempts: Attempts, registration: RecoveryStore) -> None:
        self.attempts, self.registration = attempts, registration

    def __call__(self, admission: Admission, intent: Intent) -> PendingExecution | Result:
        app = self.attempts
        try:
            prompt = app.files.read(admission.input_ref)
            schema, out = app.files.prepare(admission.key, kind(admission.step).answer_schema, intent)
            root = app.files.launch_root(admission.key, intent)
        except (EvidenceError, OSError):
            return Result(outcome=Outcome.UNAVAILABLE, explanation="The saved input or continuation artifacts are unavailable.")
        launch = app.agent.build(admission.setting, Path(admission.slot_path), kind(admission.step).environment,
                                 root, schema, out, prompt, resume=intent.session)
        if isinstance(launch, LaunchFailure):
            return Result(outcome=Outcome.UNAVAILABLE, explanation=launch.explanation)
        try:
            remaining = admission.deadline - app.clock()
            if remaining <= 0:
                return Result(outcome=Outcome.EXPIRED, explanation="The admitted execution deadline has passed.")
            return self._run(admission, intent, launch.harness, launch.spec, remaining)
        finally:
            launch.harness.cleanup()

    def _run(
        self, admission: Admission, intent: Intent, harness: Harness, spec: LaunchSpec, remaining: float,
    ) -> PendingExecution | Result:
        app = self.attempts
        callbacks: Callbacks | None = None

        def started(worker: Worker) -> None:
            nonlocal callbacks
            registered = self.registration.register(
                intent, Identity(pid=worker.pid, pgid=worker.pgid, start=worker.start, boot=worker.boot), app.clock,
            )
            if registered.outcome is not Outcome.REGISTERED or registered.intent is None:
                raise RegistrationRefused(registered.explanation)
            callbacks = Callbacks(app, admission, callback(registered.intent))

        def ref(value: str) -> None:
            if callbacks is None:
                raise RegistrationRefused("Session output preceded accepted registration.")
            callbacks.observe(value)

        stops = AgentStops(StopStore(app.registration_store.connect, app.registration_store.begin), admission, app.clock)
        duration = app.files.observe_duration(admission.key, app.monotonic, intent)
        hooks = WatchedHooks(started=started, ref=ref, unattended=False, before_stop=stops.before, after_stop=stops.after,
                             live=CommandSink(app.files, admission.key, app.clock, duration=duration))
        try:
            raw = app.execution(harness, spec, remaining, hooks)
        except (RegistrationRefused, StoreUnavailable):
            return Result(outcome=Outcome.UNAVAILABLE, explanation="Registration was not acknowledged; reconciliation is required.")
        except Exception as error:
            return Result(outcome=Outcome.UNAVAILABLE, explanation=f"Continuation execution ended unexpectedly ({type(error).__name__}).")
        finally:
            duration.seal()
        if callbacks is None:
            return Result(outcome=Outcome.UNRESOLVED, explanation="Execution returned without accepted worker registration.")
        return callbacks.returned(raw)
