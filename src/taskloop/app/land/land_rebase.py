"""The land's rebase onto the base, and the conflict it can stop on."""
from typing import Protocol

from taskloop.app.land.gate import Problem, ProblemKind
from taskloop.app.land.landed import LandedConfig
from taskloop.app.land.parts import OutcomeSteps
from taskloop.contracts.ports import Sh


class LandRebaseHost(Protocol):
    """What the land's rebase reads of the engine: the base, git and its shell, the step's outcome."""

    @property
    def cfg(self) -> LandedConfig: ...
    @property
    def sh(self) -> Sh: ...
    @property
    def steps(self) -> OutcomeSteps: ...
    def git(self, *args: str) -> str: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class LandRebase:
    def __init__(self, host: LandRebaseHost) -> None:
        self.e = host

    def run(self, fetched: int, tail: str) -> Problem | None:
        e = self.e
        rc = fetched
        if rc == 0:
            rc, tail = e.sh(["git", "rebase", "-q", e.cfg.base], pin=True)
        if not rc:
            return None
        unmerged = e.git("diff", "--name-only", "--diff-filter=U")
        if not unmerged:
            e.sh(["git", "rebase", "--abort"], pin=True)
            raise e.blocked_for(f"failed: fetch or rebase onto {e.cfg.base} failed; branch kept\n{tail}", "FAULT_LAND")
        e.steps.outcome("conflict", ", ".join(unmerged.split()))
        return Problem(ProblemKind.CONFLICT, "Conflicted files: {}\n{}".format(", ".join(unmerged.split()), tail))
