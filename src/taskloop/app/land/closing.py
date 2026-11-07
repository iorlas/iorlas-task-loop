"""Follow-up filing and cleanup capabilities bound by the run's root."""
from collections.abc import Callable

from taskloop.app.land import cleanup
from taskloop.app.land.gitcall import oneline
from taskloop.contracts.gitport import Git
from taskloop.contracts.paths import ConfigDir
from taskloop.stores.runlog import RunLog


class LandFollowUps:
    def __init__(self, filer: Callable[[], list[dict[str, str]]]) -> None:
        self.filer = filer

    def file(self) -> list[dict[str, str]]:
        return self.filer()


class LandCleanups:
    def __init__(self, git: Git, log: RunLog, cfg: ConfigDir,
                 slot_check: Callable[[str], Callable[[str], bool]], base_of: Callable[[str], str]) -> None:
        self.git, self.log, self.cfg = git, log, cfg
        self.slot_check, self.base_of = slot_check, base_of

    def retry(self, repo: str) -> None:
        cleanup.retry_logged(self.git, self.log, self.slot_check(repo), self.base_of(repo), cfg=self.cfg)


class LandHistory:
    def __init__(self, git: Git) -> None:
        self.git = git

    def since(self, wt: str, head: str, n: int) -> str:
        return oneline(self.git, wt, ["HEAD"], [head], n)
