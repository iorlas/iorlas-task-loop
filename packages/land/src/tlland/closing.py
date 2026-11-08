"""Follow-up filing and cleanup capabilities bound by the run's root."""
from collections.abc import Callable

from tlkernel.gitport import Git
from tlkernel.log import EngineLog
from tlkernel.paths import ConfigDir
from tlkernel.stagefacts import RunLogPort
from tlkernel.storeapi import Log
from tlslots.api import Effects

from tlland import cleanup
from tlland.rebase import oneline


class LandFollowUps:
    def __init__(self, filer: Callable[[], list[dict[str, str]]]) -> None:
        self.filer = filer

    def file(self) -> list[dict[str, str]]:
        return self.filer()


class LandCleanups:
    def __init__(self, git: Git, log: RunLogPort, cfg: ConfigDir,
                 slot_check: Callable[[str], Callable[[str], bool]], base_of: Callable[[str], str], *,
                 history: Log[EngineLog], fx: Effects) -> None:
        self.fx = fx
        self.history = history
        self.git, self.log, self.cfg = git, log, cfg
        self.slot_check, self.base_of = slot_check, base_of

    def retry(self, repo: str) -> None:
        cleanup.retry_logged(self.git, self.log, self.slot_check(repo), self.base_of(repo), cfg=self.cfg, history=self.history, fx=self.fx)


class LandHistory:
    def __init__(self, git: Git) -> None:
        self.git = git

    def ahead_of(self, wt: str, base: str, n: int) -> str:
        return oneline(self.git, wt, ["HEAD"], [base], n)

    def since(self, wt: str, head: str, n: int) -> str:
        return oneline(self.git, wt, ["HEAD"], [head], n)
