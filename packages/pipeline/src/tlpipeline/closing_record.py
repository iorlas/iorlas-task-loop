"""The run's log and trace at the close: the close node, the reflection, the owner's question."""
from collections.abc import Callable, Mapping
from typing import Protocol

from tlkernel import log as rec
from tlkernel import runoutcome as oc
from tlkernel.enums import Outcome
from tlkernel.ids import BeadId
from tlkernel.parks import ParkStore
from tlkernel.paths import ConfigDir
from tlkernel.run import RunFinish
from tlpipeline import outcomes
from tlpipeline.finish import outcome as finished_outcome
from tlpipeline.steps import Open
from tlpipeline.store_ports import RecordLog


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
    def finish(self, done: oc.RunOutcome, stats: str = "",
               record: Callable[[RunFinish, str], None] | None = None) -> oc.RunOutcome: ...
    def log_run(self) -> None: ...
    def file_trace(self, record: RunFinish) -> None: ...


class RecordReflector(Protocol):
    def reflect_run(self, outcome: str, why: str) -> Mapping[str, object] | None: ...


class RecordHost(Protocol):
    """What writing the run's record reads of the engine: the steps, the log, the records and the reflector; the reflection it sets."""

    reflection: Mapping[str, object] | None

    @property
    def home(self) -> ConfigDir: ...
    @property
    def bead(self) -> BeadId: ...
    @property
    def run_id(self) -> str: ...
    @property
    def log(self) -> RecordLog: ...
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
        self.host = host

    def run(self, record: RunFinish, stats: str) -> None:
        """The run's log and trace: the close node, the reflection, the owner's question."""
        e = self.host
        if self.closed():
            e.records.file_trace(record)
            return
        done = finished_outcome(record)
        outcome, why, spec, kind = done.word, done.detail, done.spec, done.kind
        e.records.log_run()
        last = e.steps.cur or e.steps.last
        if last and (e.steps.moved_from != last.n or e.steps.moved_to not in ("ask", "pause", "close")):
            to, cause = outcomes.close_move(kind)  # no move out of the run was logged from the last node: the close is it
            e.steps.move(to, cause, why.splitlines()[0][:200] if why else outcome)
        e.steps.end(outcomes.node_outcome(outcome, kind))
        e.steps.begin("close", f"close: {outcome}")
        self.close(record)
        e.steps.outcome(outcome, why.splitlines()[0][:200] if why else "")
        e.steps.end()
        e.reflection = e.reflector.reflect_run(outcome, why)  # after the close node: the outcome is decided and nothing here changes it
        e.records.file_trace(record)
        e.detail([stats] + ([why[:400]] if why else []) + (["question: " + spec.decision[:400]] if spec else []))
        if outcome is Outcome.FAILED:
            e.warn(f"task failed: {why.splitlines()[0][:200]}")

    def close(self, record: RunFinish) -> None:
        if self.closed():
            return
        retry_at = ParkStore(self.host.home).retry_at(self.host.bead, self.host.run_id)
        self.host.log.emit(rec.Close(t=record.ended, outcome=record.outcome, why_code=record.why_code, sha=record.sha,
                                  why=record.why[:500], retry_at=retry_at))

    def closed(self) -> bool:
        return any(isinstance(i.rec, rec.Close) for i in self.host.log.log.read_from(0).items)

    def stage(self, record: RunFinish, stats: str) -> None:
        """A standalone stage keeps its simple Close and trace; it does not run the whole engine's reflection."""
        self.close(record)
        self.host.records.file_trace(record)
