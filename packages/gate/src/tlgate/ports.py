"""The stores and run log the gate reads and writes through."""
from collections.abc import Callable
from typing import Protocol

from any_lease import Leases

from tlkernel.checks import BaseRedRecord, CheckRun, Durations
from tlkernel.config import HostResources
from tlkernel.log import EngineLog
from tlkernel.storeapi import Doc, DocSet, Passes


class GateStores(Protocol):
    @property
    def base_red(self) -> Callable[[str], DocSet[BaseRedRecord]]: ...
    @property
    def check_run(self) -> Callable[[str, int | None], Doc[CheckRun]]: ...
    @property
    def durations(self) -> DocSet[Durations]: ...
    @property
    def host(self) -> Doc[HostResources]: ...
    @property
    def leases(self) -> Leases: ...
    @property
    def results(self) -> Callable[[str, str], Passes]: ...


class GateLog(Protocol):
    def emit(self, rec: EngineLog) -> int: ...
    def note(self, text: str) -> int: ...
    def next_id(self, prefix: str) -> str: ...
