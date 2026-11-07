"""Narrow storage, log and shell capabilities used by land."""
from collections.abc import Callable, MutableMapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from tlkernel.profile_changes import ProfileChange
from tlkernel.queue_doc import QueueDoc
from tlkernel.queue_state import QueueState
from tlkernel.stagefacts import RunLogPort
from tlkernel.storeapi import DocSet, Log

type ProfileChanges = Log[ProfileChange]
type QueueDocs = DocSet[QueueDoc]
type QueueStates = DocSet[QueueState]


class StackLog(RunLogPort, Protocol):
    """A stack can name the bead stamped on subsequent log rows."""

    @property
    def stamp(self) -> MutableMapping[str, str]: ...


class Deadline(Protocol):
    def __call__(self, seconds: float, scope: str) -> AbstractContextManager[None]: ...


class HoldLand(Protocol):
    def __call__(self, path: Path | str, holder: str, waiting: Callable[[str], None] | None,
                 timeout: float | None) -> AbstractContextManager[Path | str]: ...


class LandLockPath(Protocol):
    def __call__(self, url: str) -> Path: ...


class IgnoreRules(Protocol):
    def __call__(self, rules: list[str], paths: list[str]) -> set[str]: ...
