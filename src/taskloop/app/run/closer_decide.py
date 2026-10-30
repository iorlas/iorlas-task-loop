"""The close's decision: the outcome's Kind after POLICY (a fault seen too often on one bead becomes one ask), the trace fields, the
fingerprint, and the storm check (never for a pause or an ask)."""
import contextlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from taskloop.adapters import ident
from taskloop.adapters import storm as storm_file
from taskloop.app.run.console import say
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.ports import Clock
from taskloop.domain import outcome as oc
from taskloop.domain import storm


class DecideHost(Protocol):
    """What the decision reads of the engine: the bead and the repo, the clock, the dry flag, git; the disposition, kind, fingerprint
    and storm banner it sets."""

    disp: oc.Disposition | None
    kind: Kind
    fp: str
    storm: str

    @property
    def bead(self) -> BeadId: ...
    @property
    def wt(self) -> str | Path: ...
    @property
    def dry(self) -> bool: ...
    @property
    def clock(self) -> Clock: ...
    def git(self, *args: str) -> str: ...
    def warn(self, text: str) -> None: ...


class Decide:
    def __init__(self, host: DecideHost) -> None:
        self.e = host

    def repo_id(self) -> str:
        return self.e.git("remote", "get-url", "origin") or str(self.e.wt)

    def run(self, o: oc.RunOutcome) -> Kind:
        """The close's Kind after POLICY. The trace fields, the fingerprint and the storm check are set here."""
        e = self.e
        e.disp = None
        kind, why = o.kind, o.detail
        now = e.clock.now()
        e.fp = o.fingerprint
        history: Sequence[Mapping[str, object]] = ()
        with contextlib.suppress(OSError):
            history = storm_file.recent_closes(ident.config_dir() / "traces.jsonl", self.repo_id(), now)
        e.disp = oc.apply(o, e.bead, history, now)
        e.kind = e.disp.kind
        if e.disp.escalated:
            e.warn(f"the same fault {oc.KNOBS['fault_retries']} times on this bead: asking the owner once")
        self.storm(history, kind, o, why)
        return e.kind

    def storm(self, history: Sequence[Mapping[str, object]], kind: Kind, o: oc.RunOutcome, why: str) -> None:
        e = self.e
        trip = storm.storm_trip(history, e.bead, kind, o.fingerprint, e.clock.now())
        if trip and not e.dry:
            path = storm_file.storm_path(ident.config_dir(), self.repo_id())
            if storm_file.write_storm(path, trip.fingerprint, trip.beads, trip.t, e.clock.now(), oc.KNOBS["storm_window_s"], why):
                e.storm = storm.banner(trip)
                e.warn(e.storm)
                say(e.storm)
