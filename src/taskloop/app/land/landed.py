"""A push that went through before the network cut its answer: the task branch's tip is the land commit and it is on the base."""
from typing import Protocol

from taskloop.app.land import cleanup
from taskloop.app.land.outbound import target
from taskloop.app.land.parts import FetchCheckout, OutcomeSteps
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Git


class LandedConfig(Protocol):
    @property
    def base(self) -> str: ...
    @property
    def land(self) -> list[str]: ...


class LandedHost(Protocol):
    """What the look for an earlier push reads of the engine: the bead, the base, git, the fetch, and the landed sha it sets."""

    landed_sha: str  # set the moment the push goes through
    land_remote_oid: str

    @property
    def bead(self) -> BeadId: ...
    @property
    def cfg(self) -> LandedConfig: ...
    @property
    def dry(self) -> bool: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def checkout(self) -> FetchCheckout: ...
    @property
    def steps(self) -> OutcomeSteps: ...
    def warn(self, text: str) -> None: ...


class Landed:
    def __init__(self, host: LandedHost) -> None:
        self.e = host

    def already(self, fetch: bool = True) -> str:
        """tl-7y6.2.13: a push that died of the network after origin took it. The task branch's tip is the land commit (titled
        `... (<bead>)`) and it is on the base: it landed, and nothing is pushed twice. -> its sha, or ''."""
        e = self.e
        if e.dry or (fetch and e.checkout.fetch()[0]):
            return ""
        last = e.git.log(e.wt, ["HEAD"], limit=1)
        if not last or not last[0].subject.endswith(f"({e.bead})"):
            return ""
        tip = last[0].oid
        want = target(e.cfg.land)
        branch = e.git.branch(e.wt) if want else ""
        e.land_remote_oid = cleanup.remote_oid(e.git, e.wt, want[0], branch) if want and branch else ""
        return tip if e.git.is_ancestor(e.wt, tip, e.cfg.base) else ""

    def found(self, sha: str) -> str:
        e = self.e
        e.landed_sha = sha
        e.steps.outcome("landed", sha[:12])
        e.warn(f"the push had already gone through ({sha[:12]} is on {e.cfg.base}): not pushed again")
        return sha
