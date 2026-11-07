"""Every store a process needs, built once at its edge and passed down: `real_stores(cfg)` or `fake_stores()`."""
import dataclasses
from collections.abc import Callable

from any_lease import Leases

from taskloop.stores.books import CheckpointBook
from tlkernel.adrs import AdrStore
from tlkernel.askstore import AskStore
from tlkernel.checks import BaseRedRecord, CheckRun, Durations
from tlkernel.config import HostResources
from tlkernel.events import Event
from tlkernel.flakes import FlakeLog
from tlkernel.followups import FollowupOutbox
from tlkernel.log import EngineLog
from tlkernel.profile_changes import ProfileChange
from tlkernel.queue_doc import QueueDoc
from tlkernel.queue_state import QueueState
from tlkernel.storeapi import Doc, DocSet, LockTable, Log, Passes, Tickets
from tlkernel.trace import RunTrace


@dataclasses.dataclass(frozen=True)
class Stores:
    run_log: Callable[[str], Log[EngineLog]]
    events: Log[Event]
    traces: Log[RunTrace]
    profile_changes: Log[ProfileChange]
    asks: AskStore
    adrs: Callable[[str], AdrStore]  # the decision store of a repo (its path)
    checkpoints: CheckpointBook
    followups: DocSet[FollowupOutbox]
    flakes: DocSet[FlakeLog]  # one per repo (repo key): the flake score log, last 30 days
    queue: DocSet[QueueDoc]  # one per repo (repo key): the merge queue's entries, builds, gates in flight; its runner thread writes
    queue_state: DocSet[QueueState]  # one per repo (repo key): the tree assertion's incidents and the queue's freeze flag
    results: Callable[[str, str], Passes]  # the passes of a check of a repo (repo key, check id), one per run key
    base_red: Callable[[str], DocSet[BaseRedRecord]]  # whether a check was red on its base, one per run key (repo key)
    durations: DocSet[Durations]  # one per repo
    check_run: Callable[[str, int | None], Doc[CheckRun]]  # a run's round (None: its latest)
    host: Doc[HostResources]  # this machine's own file (resources it has); a person writes it
    locks: LockTable
    leases: Leases  # engine.resources: counting leases across processes (any_lease), shared with manual runs
    tickets: Tickets
