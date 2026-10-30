"""A resume rebase that stopped on a few files: one fix round (markers and build only) in place of throwing the branch away."""
from pathlib import Path
from typing import Protocol

from taskloop.app.land.rebase import Rebase
from taskloop.contracts.ports import Sh
from taskloop.stores.runlog import RunLog


class SalvageFixer(Protocol):
    def fix(self, kind: str, tail: str, resume: bool = ...) -> str: ...


class SalvageHost(Protocol):
    """What the salvage reads of the engine: git and its shell, the conflict's words and the head before the rebase, the one fix round it
    may ask for (the land's own two stay as they were)."""

    rebase_orig: str
    salvage_tail: str
    salvaged: bool
    fixes: int

    @property
    def FixFailed(self) -> type[Exception]: ...
    @property
    def sh(self) -> Sh: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def fixer(self) -> SalvageFixer: ...
    def git(self, *args: str) -> str: ...
    def warn(self, text: str) -> None: ...


class Salvage:
    def __init__(self, host: SalvageHost, rebase: Rebase) -> None:
        self.e = host
        self.rebase = rebase

    def salvage(self) -> str:
        """tl-7y6.2.19: the resume rebase stopped on a few files: one fix(conflict) round (markers and build only) instead of throwing the
        branch away. -> "rebased" (the run record shows salvaged: true), or "conflict": the fix did not work, the branch is back as it
        was and the caller starts again."""
        e = self.e
        fixes, ok = e.fixes, False
        try:
            d = e.fixer.fix("conflict", e.salvage_tail, resume=True)
            ok = not e.git("diff", "--name-only", "--diff-filter=U")  # (a fix the review sent back still continued the rebase)
            if d != "accept":
                e.warn("resume: the conflict fix did not pass its checks and review; the stage goes on from it")
        except e.FixFailed as err:
            e.warn(f"the resume conflict fix failed: {str(err).splitlines()[0][:200]}")
        finally:
            e.fixes = fixes  # the land's two fix rounds are its own
        gd = Path(e.git("rev-parse", "--absolute-git-dir") or ".")
        if (gd / "rebase-merge").exists() or (gd / "rebase-apply").exists():
            e.sh(["git", "rebase", "--abort"], pin=True)
        if not ok:
            e.sh(["git", "reset", "-q", "--hard", e.rebase_orig], pin=True)  # the work as it was, for start_again
            return "conflict"
        e.salvaged = True
        self.rebase.follow_checkpoint()
        e.log.note("resume conflict fixed in place instead of starting again (salvaged)")
        return self.rebase.plan_count()
