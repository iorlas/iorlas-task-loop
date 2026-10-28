"""Every store a process needs, built once at its edge and passed down: `real_stores(cfg)` or `fake_stores()`."""
import dataclasses
from collections.abc import Callable

from taskloop.contracts.events import Event
from taskloop.contracts.log import EngineLog
from taskloop.contracts.loop import LoopCommand, LoopState, Rest
from taskloop.contracts.stores import AskStore
from taskloop.contracts.trace import RunTrace
from taskloop.stores.api import Doc, LockTable, Log, Tickets
from taskloop.stores.books import CheckpointBook


@dataclasses.dataclass(frozen=True)
class Stores:
    run_log: Callable[[str], Log[EngineLog]]
    events: Log[Event]
    traces: Log[RunTrace]
    asks: AskStore
    checkpoints: CheckpointBook
    loop_state: Callable[[str], Doc[LoopState]]
    loop_command: Callable[[str], Doc[LoopCommand]]
    loop_rest: Callable[[str], Doc[Rest]]
    locks: LockTable
    tickets: Tickets
