"""The close's decision: the outcome's Kind after POLICY (a fault seen too often on one bead becomes one ask), the trace fields, the
fingerprint, and the storm check (never for a pause or an ask)."""
import traceback
from collections.abc import Mapping, Sequence
from typing import Protocol

from taskloop.adapters import storm as storm_file
from taskloop.adapters.repourl import repo_url
from taskloop.contracts.gitport import Git
from taskloop.contracts.ids import BeadId
from taskloop.contracts.kinds import Kind
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Clock
from taskloop.contracts.stagefacts import Narrate
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
    def wt(self) -> str: ...
    @property
    def home(self) -> ConfigDir: ...
    @property
    def git(self) -> Git: ...
    @property
    def dry(self) -> bool: ...
    @property
    def clock(self) -> Clock: ...
    def warn(self, text: str) -> None: ...


class Decide:
    def __init__(self, host: DecideHost, say: Narrate) -> None:
        self.host = host
        self.say = say

    def repo_id(self) -> str:
        return repo_url(self.host.git, self.host.wt)

    def run(self, o: oc.RunOutcome) -> Kind:
        """The close's Kind after POLICY. The trace fields, the fingerprint and the storm check are set here."""
        host = self.host
        host.disp = None
        kind, why = o.kind, o.detail
        now = host.clock.now()
        host.fp = o.fingerprint
        history: Sequence[Mapping[str, object]] = ()
        try:
            history = storm_file.recent_closes(self.host.home.traces(), self.repo_id(), now)
        except OSError as err:
            host.warn(f"could not read retry history: {err}\n" + traceback.format_exc())
        host.disp = oc.apply(o, host.bead, history, now)
        host.kind = host.disp.kind
        if host.disp.escalated:
            host.warn(f"the same fault {oc.KNOBS['fault_retries']} times on this bead: asking the owner once")
        if o.rule.storm:
            self.storm(history, kind, o, why)
        return host.kind

    def storm(self, history: Sequence[Mapping[str, object]], kind: Kind, o: oc.RunOutcome, why: str) -> None:
        host = self.host
        trip = storm.storm_trip(history, host.bead, kind, o.fingerprint, host.clock.now())
        if trip and not host.dry:
            path = storm_file.storm_path(host.home.root, self.repo_id())
            if storm_file.write_storm(path, trip.fingerprint, trip.beads, trip.t, host.clock.now(), oc.KNOBS["storm_window_s"], why):
                host.storm = storm.banner(trip, str(path))
                host.warn(host.storm)
                self.say.note(host.storm)
