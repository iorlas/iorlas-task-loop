"""Store capabilities owned by the pipeline; implementations are bound at the root."""
import sqlite3
from collections.abc import Callable
from typing import Protocol

from tlkernel.ask import Ask
from tlkernel.checkpoint import Checkpoint
from tlkernel.checks import CheckRun
from tlkernel.docstore import Ledger, Page
from tlkernel.followups import FollowupOutbox
from tlkernel.ids import BeadId
from tlkernel.log import EngineLog
from tlkernel.paths import ConfigDir
from tlkernel.stagefacts import RunLogPort
from tlkernel.trace import RunTrace


class ReadDoc[T](Protocol):
    def get(self) -> T | None: ...


class WriteDoc[T](ReadDoc[T], Protocol):
    def write(self, rec: T) -> None: ...


class PendingDoc(Protocol):
    def need(self) -> FollowupOutbox | None: ...
    def write(self, rec: FollowupOutbox) -> None: ...


class CheckpointDoc(WriteDoc[Checkpoint], Protocol):
    def need(self) -> Checkpoint | None: ...
    def delete(self) -> None: ...
    def modify(self, fn: Callable[[Checkpoint], Checkpoint]) -> bool: ...
    def modify_with(self, fn: Callable[[Checkpoint], Checkpoint],
                    also: Callable[[sqlite3.Connection | None], None]) -> bool: ...


class CheckpointBook(Protocol):
    def of(self, bead: str) -> CheckpointDoc: ...


class PendingBook(Protocol):
    def of(self, key: str) -> PendingDoc: ...


class CheckpointStores(Protocol):
    @property
    def checkpoints(self) -> CheckpointBook: ...
    @property
    def followups(self) -> PendingBook: ...


class TraceReader(Protocol):
    def read_from(self, offset: int = 0, limit: int | None = None) -> Page[RunTrace]: ...


class WaitStores(Protocol):
    @property
    def traces(self) -> TraceReader: ...


class StageStores(Protocol):
    @property
    def traces(self) -> Ledger[RunTrace]: ...
    @property
    def run_log(self) -> Callable[[str], Ledger[EngineLog]]: ...


class StandaloneStores(StageStores, Protocol):
    @property
    def check_run(self) -> Callable[[str, int | None], WriteDoc[CheckRun]]: ...


class LogFactory[L: RunLogPort](Protocol):
    def __call__(self, log: Ledger[EngineLog], run_id: str, machine: str, /) -> L: ...


class StoresFactory[S: StageStores](Protocol):
    def __call__(self, cfg: ConfigDir) -> S: ...


class EngineLogReader(Protocol):
    def read_from(self, offset: int = 0, limit: int | None = None) -> Page[EngineLog]: ...


class RecordLog(RunLogPort, Protocol):
    @property
    def log(self) -> EngineLogReader: ...


class NotesAsks(Protocol):
    def get(self, bead: BeadId) -> Ask | None: ...
    def close(self, bead: BeadId, ask_id: str, why: str, now: float = ...) -> bool: ...


class NotesStores(Protocol):
    @property
    def asks(self) -> NotesAsks: ...
