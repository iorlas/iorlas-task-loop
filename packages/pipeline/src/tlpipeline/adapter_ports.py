"""Pipeline capabilities implemented by adapters and bound at the application root."""
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from tlkernel.bead import Bead
from tlkernel.beadsport import Beads
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.ids import BeadId


class LastEvent(Protocol):
    def __call__(self, path: str | Path) -> float: ...


class PeekBead(Protocol):
    def __call__(self, store: Beads, bead: BeadId, /) -> Bead | None: ...


class Version(Protocol):
    def __call__(self) -> str: ...


class DelegateEnv(Protocol):
    def __call__(self, env: Env) -> dict[str, str]: ...


class ChildEnv(Protocol):
    def exec_env(self, env: Env, handover: Mapping[EnvVar, str]) -> dict[str, str]: ...
    def script_argv(self, script: str | Path, env: Env) -> list[str]: ...


class Install(Protocol):
    @property
    def PLUGIN_ROOT(self) -> Path: ...
    def plugin_version(self) -> str: ...


class Deadline(Protocol):
    def remaining(self, seconds: float) -> float: ...
    def check(self) -> None: ...


class RecentCloses(Protocol):
    def __call__(self, traces: str | Path, repo: str, now: float) -> Sequence[Mapping[str, object]]: ...


class Attempt(Protocol):
    def __call__[**P](self, call: Callable[P, object], *args: P.args, **kw: P.kwargs) -> bool: ...


class DeadlineScope(Protocol):
    def __call__(self, seconds: float, scope: str) -> AbstractContextManager[None]: ...
