"""Observe a release's registered processes. No stop action is authorized by a liveness observation."""

from dataclasses import dataclass
from typing import Literal

from any_agent.procs import Worker
from stream_proc import OwnedProcess

from taskloop.attempt_types import EntryIdentity, Observe, WorkerGone
from taskloop.setup_store import SetupSeen

NOTHING = "Nothing changed."


@dataclass(frozen=True)
class NotReleased:
    """A refusal, or an unknown/unsettled observation; detail says what changed."""

    kind: Literal["refused", "unavailable", "unsettled"]
    reason: str
    detail: str = NOTHING

    @property
    def word(self) -> str:
        return f"{self.kind}:{self.reason}"


@dataclass(frozen=True)
class Stopping:
    phase: str
    entry: EntryIdentity | None
    worker: Worker | None


def entry_stopped(
    observe: Observe, me: EntryIdentity | None, entry: EntryIdentity | None, process: str | None = None,
) -> NotReleased | None:
    """A matching entry refuses release unless releasing itself; unknown observation preserves custody."""
    if entry is None or entry == me:
        return None
    seen = observe(entry)
    if seen == "matching":
        running = f"The {process or "attempt's entry"} runs as pid {entry[0]}: wait, or stop it by verified pid. {NOTHING}"
        return NotReleased("refused", "entry_running", running)
    unknown = f"The {process or 'registered entry'} could not be observed. {NOTHING}"
    return NotReleased("unavailable", "observe", unknown) if seen == "unknown" else None


def worker_stopped(gone: WorkerGone, phase: str, worker: Worker | None) -> NotReleased | None:
    """The exact registered identity and its group must be gone; unknown counts as alive."""
    if worker is None:
        unknown = "Dispatched with no agent recorded: it cannot be shown stopped; the whole-DB discard is the only way out."
        return None if phase == "admitted" else NotReleased("unsettled", "worker_unknown", f"{unknown} {NOTHING}")
    alive = f"The agent (pid {worker.pid}, process group {worker.pgid}) or its group may run: stop it by verified pid. {NOTHING}"
    return None if gone(worker) else NotReleased("unsettled", "worker_alive", alive)


def stop_proof(observe: Observe, gone: WorkerGone, me: EntryIdentity | None, row: Stopping) -> NotReleased | None:
    return entry_stopped(observe, me, row.entry) or worker_stopped(gone, row.phase, row.worker)


def setup_stopped(seen: SetupSeen, setup: OwnedProcess | None) -> NotReleased | None:
    """The latest unsettled setup command must be gone with an empty group, or belong to another boot."""
    found = "gone" if setup is None else seen(setup)
    if setup is None or found == "gone":
        return None
    if found == "unknown":
        return NotReleased("unavailable", "setup_unknown", f"The slot's setup could not be observed. {NOTHING}")
    alive = f"The slot's setup (process group {setup.pgid}, recorded this boot) still runs: wait, or see the guide. {NOTHING}"
    return NotReleased("unsettled", "setup_running", alive)
