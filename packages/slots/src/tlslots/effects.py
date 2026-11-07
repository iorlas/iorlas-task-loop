"""Machine effects supplied by the composition root."""
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tlkernel.lockenums import LockWhat
from tlkernel.locks import LockRecord


class ProcAlive(Protocol):
    def __call__(self, pid: object, start: str = "") -> bool: ...


class HoldPath(Protocol):
    def __call__(self, path: Path | str, holder: str, *, what: LockWhat = LockWhat.LAND,
                 timeout: float | None = None, waiting: Callable[[LockRecord | None], None] | None = None,
                 check: Callable[[], None] | None = None) -> AbstractContextManager[LockRecord]: ...


@dataclass(frozen=True)
class Effects:
    hostname: Callable[[], str]
    proc_alive: ProcAlive
    proc_start: Callable[[object], str]
    hold_path: HoldPath
    running_for: Callable[[str], list[str]]
