"""BaseCheck: was this check already red before the task touched anything? Asked once per check and base commit."""
import time
from pathlib import Path

from taskloop.adapters.base_tree import base_tree
from taskloop.app.checks.cache import RunMemo
from taskloop.app.checks.host import CheckHost
from taskloop.contracts.argv import argv_of
from taskloop.contracts.checks import Check
from taskloop.domain.checks.names import norm


class BaseCheck:
    def __init__(self, host: CheckHost, memo: RunMemo, enabled: bool) -> None:
        self.host, self.memo = host, memo
        self.sha = str(memo.base) if enabled else ""  # no sha, no base run (the gate's tree is the rebased one: a red is red)

    def red(self, c: Check) -> bool:
        """Run the check once on a clean checkout of the base commit; red there too: the task did not break it, so it is not the
        writer's. The run is bounded by the check's wall limit; the answer is remembered by base sha. Off with engine.base_red: false."""
        if not self.host.cfg.base_red or not self.sha:
            return False
        known = self.memo.base_was_red(c)
        if known is not None:
            return known
        dest = self.host.run_dir / "base" / self.sha[:12]
        dest.parent.mkdir(parents=True, exist_ok=True)
        with base_tree(self.host.git, self.host.wt, self.sha, dest) as tree:
            red = tree is not None and self._rc(tree, c) not in (0, None)
        self.memo.set_base_red(c, red)
        if red:
            self.host.warn(f"`{c.id}` is red on the untouched base too: not the writer's, the round does not count it")
        return red

    def _rc(self, tree: Path, c: Check) -> int | None:
        started = time.time()
        rc, _ = self.host.sh(argv_of(c.cmd), timeout=c.wall_min * 60, save=None, env=None, cwd=tree)
        self.host.log.note(f"base run of `{norm(c.cmd)[:80]}`: exit {rc} in {time.time() - started:.0f} s ({self.sha[:12]})")
        return None if self.host.killed else rc
