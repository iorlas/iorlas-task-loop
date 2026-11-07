"""What the land's steps share: its counters between tries, and the words for where a try stands."""

import contextlib
import time
from collections.abc import Generator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from tlkernel import log as rec
from tlkernel.plancheck import PlanCheck

from taskloop.stores.runlog import RunLog

PUSH_UP_FAILS = 3  # network errors on the push while the probe says the network is up: not the network's to cure (a proxy, DNS)
PUSH_TRIES = 3  # a push rejected because main moved is tried again this often


class Phase(Enum):
    """Where the land stands between its tries (one state, not two flags)."""

    FRESH = "fresh"
    STEP_OPEN = "step open"  # the outside gate's land step is still open: the lock's first try goes on in it
    NET_DOWN = "net down"  # the last push died of the network: look again before pushing


class Placing(Enum):
    """Where the gate runs for the push in the lock."""

    NO_GATE = ""
    CACHED = "cached"  # it passed on this tree and base
    STALE = "stale"  # main moved under the outside gate: let the lock go, gate outside again
    INSIDE = "inside"  # the tries are used up: gate here, as a busy main must not starve a bead
    OUTSIDE = "outside"


class Next(Enum):
    """What a push that did not land asks of the land."""

    AGAIN = "again"  # rejected: main moved, try again in this lock
    REST = "rest"  # a network error: rest first


@dataclass
class Land:
    """What survives from one try of the land to the next."""

    pushes: int = 0  # rejected pushes so far
    flaky: int = 0  # network errors on the push while the network looked up
    phase: Phase = Phase.FRESH
    moved: int = 0  # times the lock was let go because main moved under the gate: the gate runs outside again (land_optimistic_tries)
    stale: int = 0  # in-lock STALE answers, independent of optimistic retries
    iterations: int = 0  # complete land cycles, including outside fixes and network waits
    attempts: int = 0  # every outside or in-lock attempt, even when no push was reached


class LandState:
    """What the land and its resume rebase keep between their steps and do not save: the gate's first red log, the rebase's heads and
    conflict words, whether a conflict was fixed in place, and the task ref checked before the push (docs/design/b-land.md, slice 2)."""

    def __init__(self) -> None:
        self.gate_log: Path | None = None  # the log of the first red step, for the fix round
        self.salvage_tail = ""  # the conflict's words for the fix round
        self.rebase_orig = ""  # the branch's head before the rebase, for a fresh attempt
        self.rebase_pre: list[str] = []  # the heads the checkpoint may name before the rebase
        self.salvaged = False  # a resume conflict was fixed in place, not by starting again (tl-7y6.2.19)
        self.remote_oid = ""  # the task ref checked before the push; cleanup retains this lease


class BeginSteps(Protocol):
    def begin(self, step: str, text: str, **meta: object) -> int: ...


class OutcomeSteps(Protocol):
    def outcome(self, outcome: str, detail: str = ...) -> None: ...


class MoveSteps(Protocol):
    def move(self, to: str, cause: str, detail: str = ...) -> None: ...


class OutcomeMoveSteps(OutcomeSteps, MoveSteps, Protocol):
    pass


class FetchCheckout(Protocol):
    def fetch(self, check: bool = ...) -> tuple[int, str]: ...


class StageCheckout(Protocol):
    def stage_all(self, check: bool = ..., everything: bool = ...) -> int: ...


class Strays(Protocol):
    def quarantine_strays(self) -> list[str]: ...


class Net(Protocol):
    def net_up(self) -> bool | None: ...
    def await_net(self, up: bool | None, max_s: float) -> tuple[float, bool]: ...


class NetWorker(Protocol):
    @property
    def acts(self) -> Net: ...


class LandLocks(Protocol):
    def locked(self, what: str, path: Path | str, holder: str | None = ...) -> AbstractContextManager[Path | str]: ...


class CaseChecks(Protocol):
    def case_checks(self) -> Sequence[PlanCheck]: ...


@contextlib.contextmanager
def phase(log: RunLog, name: str, *, wait: bool = False) -> Generator[None]:
    """Time the body as the step `land:<name>`; its seconds are `wait_seconds` for a wait, else `exec_seconds`."""
    step = f"land:{name}"
    sid = log.next_id("s")
    log.emit(rec.StepStart(id=sid, step=step))
    t0 = time.monotonic()
    outcome = "done"
    try:
        yield
    except BaseException:
        outcome = "failed"
        raise
    finally:
        secs = time.monotonic() - t0
        log.emit(rec.StepEnd(id=sid, step=step, outcome=outcome, wait_seconds=secs if wait else None, exec_seconds=None if wait else secs))
