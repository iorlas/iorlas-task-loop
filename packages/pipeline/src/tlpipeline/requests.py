"""Consume owner requests at the run's beat and step boundaries."""

import contextlib
import time
from typing import Protocol

from tlkernel import factorydb
from tlkernel import log as rec
from tlkernel.kinds import Kind
from tlkernel.paths import ConfigDir
from tlkernel.requests import OwnerNote, OwnerRequest
from tlkernel.signalrows import SignalRows
from tlpipeline.blocked import Blocked

PARKED_WHY = "parked: by the owner (the branch and the checkpoint are kept; release the hold to go on)"
STOPPED_WHY = "failed: stopped by the owner"
NOTE_HEAD = "\n\n## The owner's note for this stage\n"


def take(cfg: ConfigDir, run: str, now: float = 0.0) -> OwnerRequest | None:
    """The run's pending request, taken: each is acted on once."""
    return SignalRows(cfg, run).take(now or time.time())


def peek(cfg: ConfigDir, run: str) -> OwnerRequest | None:
    return SignalRows(cfg, run).peek()


class RequestHalt(Protocol):
    def set(self) -> None: ...


class RequestLog(Protocol):
    def emit(self, record: rec.Said, /) -> object: ...


class RequestSteps(Protocol):
    def move(self, to: str, cause: str, detail: str = "") -> None: ...


class RequestsHost(Protocol):
    """Only the run state and actions consumed at owner-request boundaries."""

    @property
    def home(self) -> ConfigDir: ...
    @property
    def run_id(self) -> str: ...
    @property
    def halt(self) -> RequestHalt: ...
    @property
    def log(self) -> RequestLog: ...
    @property
    def steps(self) -> RequestSteps: ...

    def step_id(self) -> str: ...
    def halt_point(self) -> None: ...


class OwnerRequests:
    """The run's side: what it does with the owner's requests."""

    def __init__(self, host: RequestsHost) -> None:
        self.host = host
        self.notes: list[OwnerNote] = []  # taken, for the next worker call's prompt
        self.stopped = False  # the owner's stop set the stop flag: the close names the owner, not a SIGTERM
        self.closing = False  # the close-out began: nothing is taken any more (a step of the close-out is no safe point to end at)

    @property
    def cfg(self) -> ConfigDir:
        return self.host.home

    @property
    def run(self) -> str:
        return self.host.run_id

    def at_beat(self) -> None:
        """A stop is acted on now: the run's stop flag, as a SIGTERM sets it. The file stays for the step boundary to take."""
        got = None if self.closing else peek(self.cfg, self.run)
        if got is not None and got.stop and not self.stopped:
            self.stopped = True
            self.host.halt.set()

    def at_step(self, step: str) -> None:
        """A step boundary (a safe point): take the file; a stop or a park ends the run here, notes wait for the next worker call."""
        got = None if self.closing else take(self.cfg, self.run)
        if got is None:
            return
        for n in got.notes:
            self.host.log.emit(rec.Said(step=self.host.step_id(), who="owner", text=n.text))
        self.notes += got.notes
        if got.stop:
            self.stopped = True
            self.host.halt.set()
            self.host.halt_point()
        if got.park:
            self.host.steps.move("pause", Kind.OWNER_PARK.value, f"the owner parked it before {step}")
            raise Blocked(PARKED_WHY, kind=Kind.OWNER_PARK)

    def prompt_tail(self) -> str:
        """The notes taken since the last worker call, as the prompt's last section; then they are given."""
        if not self.notes:
            return ""
        text = NOTE_HEAD + "\n".join(f"- {n.text}" for n in self.notes) + "\n"
        self.notes = []
        return text

    def drop(self) -> None:
        """At the close: a request the run did not take is for a run that has ended; it is dropped, never acted on later."""
        self.closing = True
        with contextlib.suppress(OSError, factorydb.DatabaseError):
            take(self.cfg, self.run)
