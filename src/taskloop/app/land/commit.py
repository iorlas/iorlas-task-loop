"""The land's one commit per task, titled after the bead: earlier runs' wip commits are folded in."""
from typing import Protocol

from taskloop.app.land.gitcall import must
from taskloop.app.land.parts import StageCheckout, Strays
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Git


class CommitPictures(Protocol):
    def copy_looks(self) -> object: ...


class CommitHost(Protocol):
    """What the commit reads of the engine: the bead, git, the pictures, the staging and the strays."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def pictures(self) -> CommitPictures: ...
    @property
    def checkout(self) -> StageCheckout: ...
    @property
    def newfiles(self) -> Strays: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class Commit:
    def __init__(self, host: CommitHost) -> None:
        self.e = host

    def run(self, bead: Bead, base_ref: str) -> bool:
        """One commit per task, titled after the bead. -> False: the wip commits add up to nothing."""
        e = self.e
        base = e.git.merge_base(e.wt, "HEAD", base_ref)
        if base:
            must(e, f"reset --soft {base}", lambda: e.git.reset(e.wt, base, "soft"))
        e.pictures.copy_looks()
        e.checkout.stage_all(check=True)
        e.newfiles.quarantine_strays()
        if base and not e.git.staged(e.wt):
            return False
        done = e.git.try_commit(e.wt, f"{bead.title[:72]} ({e.bead})")
        if not done.ok:
            raise e.blocked_for("failed: commit refused (hooks)\n" + done.output, "FAULT_LAND")
        return True
