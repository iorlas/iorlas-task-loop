"""The run's log and trace at the close: the close node, the reflection, the owner's question."""
from collections.abc import Mapping
from typing import Protocol

from taskloop.app.run import outcomes
from taskloop.app.run import trace as runtrace
from taskloop.app.run.steps import Open
from taskloop.contracts import log as rec
from taskloop.contracts.enums import Outcome
from taskloop.domain import outcome as oc
from taskloop.stores.runlog import RunLog


class RecordSteps(Protocol):
    @property
    def cur(self) -> Open | None: ...
    @property
    def last(self) -> Open | None: ...
    @property
    def moved_from(self) -> int | None: ...
    @property
    def moved_to(self) -> str | None: ...
    def move(self, to: str, cause: str, detail: str = ...) -> None: ...
    def begin(self, step: str, text: str, **meta: object) -> int: ...
    def outcome(self, outcome: str, detail: str = ...) -> None: ...
    def end(self, outcome: str = ...) -> None: ...


class RecordRecords(Protocol):
    def log_run(self) -> None: ...
    def file_trace(self, outcome: Outcome, why: str, sha: str) -> None: ...


class RecordReflector(Protocol):
    def reflect_run(self, outcome: str, why: str) -> Mapping[str, object] | None: ...


class RecordHost(Protocol):
    """What writing the run's record reads of the engine: the steps, the log, the records and the reflector; the reflection it sets."""

    reflection: Mapping[str, object] | None

    @property
    def log(self) -> RunLog: ...
    @property
    def steps(self) -> RecordSteps: ...
    @property
    def records(self) -> RecordRecords: ...
    @property
    def reflector(self) -> RecordReflector: ...
    def detail(self, lines: list[str]) -> None: ...
    def warn(self, text: str) -> None: ...


class RecordRun:
    def __init__(self, host: RecordHost) -> None:
        self.e = host

    def run(self, done: oc.RunOutcome, stats: str) -> None:
        """The run's log and trace: the close node, the reflection, the owner's question."""
        e = self.e
        outcome, why, sha, spec, kind = done.word, done.detail, done.sha, done.spec, done.kind
        e.records.log_run()
        last = e.steps.cur or e.steps.last
        if last and (e.steps.moved_from != last.n or e.steps.moved_to not in ("ask", "pause", "close")):
            to, cause = outcomes.close_move(kind)  # no move out of the run was logged from the last node: the close is it
            e.steps.move(to, cause, why.splitlines()[0][:200] if why else outcome)
        e.steps.end(outcomes.node_outcome(outcome, kind))
        e.steps.begin("close", f"close: {outcome}")
        code = runtrace.why_code(kind.value, outcome)
        e.log.emit(rec.Close(outcome=Outcome(outcome), why_code=code, sha=sha or "", why=why[:500]))
        e.steps.outcome(outcome, why.splitlines()[0][:200] if why else "")
        e.steps.end()
        e.reflection = e.reflector.reflect_run(outcome, why)  # after the close node: the outcome is decided and nothing here changes it
        e.records.file_trace(outcome, why, sha)
        e.detail([stats] + ([why[:400]] if why else []) + (["question: " + spec.decision[:400]] if spec else []))
        if outcome is Outcome.FAILED:
            e.warn(f"task failed: {why.splitlines()[0][:200]}")
