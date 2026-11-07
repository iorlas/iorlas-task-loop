"""The close's decision: the outcome's Kind after POLICY (a fault seen too often on one bead becomes one ask), the trace fields, the
fingerprint."""
import traceback
from collections.abc import Mapping, Sequence
from typing import Protocol

from tlkernel.gitport import Git
from tlkernel.ids import BeadId
from tlkernel.kinds import Kind
from tlkernel.paths import ConfigDir
from tlkernel.ports import Clock
from tlkernel.repourl import repo_url

from taskloop.app.pipeline.adapter_ports import RecentCloses
from taskloop.domain import outcome as oc


class DecideHost(Protocol):
    """What the decision reads of the engine: the bead and the repo, the clock, git; the disposition, kind, fingerprint
    it sets."""

    disp: oc.Disposition | None
    kind: Kind
    fp: str

    @property
    def bead(self) -> BeadId: ...
    @property
    def wt(self) -> str: ...
    @property
    def home(self) -> ConfigDir: ...
    @property
    def git(self) -> Git: ...
    @property
    def clock(self) -> Clock: ...
    def warn(self, text: str) -> None: ...


class Decide:
    def __init__(self, context: DecideHost, recent_closes: RecentCloses) -> None:
        self.host = context
        self.recent_closes = recent_closes

    def repo_id(self) -> str:
        return repo_url(self.host.git, self.host.wt)

    def run(self, o: oc.RunOutcome) -> Kind:
        """The close's Kind after POLICY. The trace fields and fingerprint are set here."""
        host = self.host
        host.disp = None
        now = host.clock.now()
        host.fp = o.fingerprint
        history: Sequence[Mapping[str, object]] = ()
        try:
            history = self.recent_closes(self.host.home.traces(), self.repo_id(), now)
        except OSError as err:
            host.warn(f"could not read retry history: {err}\n" + traceback.format_exc())
        host.disp = oc.apply(o, host.bead, history, now)
        host.kind = host.disp.kind
        if host.disp.escalated:
            host.warn(f"the same fault {oc.KNOBS['fault_retries']} times on this bead: asking the owner once")
        return host.kind
