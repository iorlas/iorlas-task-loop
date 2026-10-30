"""The land's one commit per task, titled after the bead: earlier runs' wip commits are folded in."""
from typing import Protocol

from taskloop.app.land.parts import StageCheckout, Strays
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Sh


class CommitPictures(Protocol):
    def copy_looks(self) -> object: ...


class CommitHost(Protocol):
    """What the commit reads of the engine: the bead, git and its shell, the pictures, the staging and the strays."""

    @property
    def bead(self) -> BeadId: ...
    @property
    def sh(self) -> Sh: ...
    @property
    def pictures(self) -> CommitPictures: ...
    @property
    def checkout(self) -> StageCheckout: ...
    @property
    def newfiles(self) -> Strays: ...
    def git(self, *args: str) -> str: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class Commit:
    def __init__(self, host: CommitHost) -> None:
        self.e = host

    def run(self, bead: Bead, base_ref: str) -> bool:
        """One commit per task, titled after the bead. -> False: the wip commits add up to nothing."""
        e = self.e
        base = e.git("merge-base", "HEAD", base_ref)
        if base:
            e.sh(["git", "reset", "-q", "--soft", base], check=True, pin=True)
        e.pictures.copy_looks()
        e.checkout.stage_all(check=True)
        e.newfiles.quarantine_strays()
        if base and not e.sh(["git", "diff", "--cached", "--quiet"], pin=True)[0]:
            return False
        rc, tail = e.sh(["git", "commit", "-q", "-m", f"{bead.title[:72]} ({e.bead})"], pin=True)
        if rc:
            raise e.blocked_for("failed: commit refused (hooks)\n" + tail, "FAULT_LAND")
        return True
