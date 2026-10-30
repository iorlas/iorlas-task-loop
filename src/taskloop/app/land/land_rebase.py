"""The land's rebase onto the base, and the conflict it can stop on."""
from typing import Protocol

from taskloop.app.land.gate import Problem, ProblemKind
from taskloop.app.land.landed import LandedConfig
from taskloop.app.land.parts import OutcomeSteps
from taskloop.contracts.ports import Git


class LandRebaseHost(Protocol):
    """What the land's rebase reads of the engine: the base, git, the step's outcome."""

    @property
    def cfg(self) -> LandedConfig: ...
    @property
    def git(self) -> Git: ...
    @property
    def wt(self) -> str: ...
    @property
    def steps(self) -> OutcomeSteps: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


class LandRebase:
    def __init__(self, host: LandRebaseHost) -> None:
        self.e = host

    def run(self, fetched: int, tail: str) -> Problem | None:
        e = self.e
        ok = fetched == 0
        if ok:
            done = e.git.rebase(e.wt, e.cfg.base)
            ok, tail = done.ok, done.output
        if ok:
            return None
        unmerged = e.git.unmerged(e.wt)
        if not unmerged:
            e.git.rebase_abort(e.wt)
            raise e.blocked_for(f"failed: fetch or rebase onto {e.cfg.base} failed; branch kept\n{tail}", "FAULT_LAND")
        e.steps.outcome("conflict", ", ".join(unmerged))
        return Problem(ProblemKind.CONFLICT, "Conflicted files: {}\n{}".format(", ".join(unmerged), tail))
