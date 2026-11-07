"""Narrow storage and log capabilities used by land."""
from collections.abc import MutableMapping
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
