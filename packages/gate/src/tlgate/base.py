"""BaseCheck: was this check already red before the task touched anything? Asked once per check and base commit."""
import threading
import time
from pathlib import Path

from tlkernel.argv import argv_of
from tlkernel.checks import Check

from tlgate.base_tree import base_tree
from tlgate.cache import RunnerMemo
from tlgate.domain.names import norm
from tlgate.host import CheckHost


class BaseCheck:
    def __init__(self, host: CheckHost, memo: RunnerMemo, enabled: bool) -> None:
        self.host, self.memo = host, memo
        self.lock = threading.Lock()
        self.sha = str(memo.base) if enabled else ""  # no sha, no base run (the gate's tree is the rebased one: a red is red)

    def red(self, c: Check, stop: threading.Event | None = None) -> bool:
        """Run the check once on a clean checkout of the base commit; red there too: the task did not break it, so it is not the
        writer's. The run is bounded by the check's wall limit; the answer is remembered by base sha. Off with engine.base_red: false.
        Never for a pass_files check: the base has other files, not the ones it was handed."""
        if c.pass_files or not self.host.cfg.base_red or not self.sha:
            return False
        with self.lock:  # two tracks may both be red: one clean checkout of the base at a time
            return self._red(c, stop)

    def _red(self, c: Check, stop: threading.Event | None) -> bool:
        known = self.memo.base_was_red(c)
        if known is not None:
            return known
        dest = self.host.run_dir / "base" / self.sha[:12]
        dest.parent.mkdir(parents=True, exist_ok=True)
        with base_tree(self.host.git, self.host.wt, self.sha, dest) as tree:
            red = tree is not None and self._rc(tree, c, stop) not in (0, None)
        if stop is not None and stop.is_set():  # stopped half way: nothing was learned about the base
            return False
        self.memo.set_base_red(c, red)
        if red:
            self.host.warn(f"`{c.id}` is red on the untouched base too: not the writer's, the round does not count it")
        return red

    def _rc(self, tree: Path, c: Check, stop: threading.Event | None) -> int | None:
        started = time.time()
        try:
            rc, _ = self.host.sh(argv_of(c.cmd), timeout=c.wall_min * 60, save=None, env=c.env, cwd=tree, stop=stop,
                                 what="check", network=c.network)
            killed = self.host.killed
        except OSError as error:
            killed = False
            rc = 127 if isinstance(error, FileNotFoundError) else 126
        self.host.log.note(f"base run of `{norm(c.cmd)[:80]}`: exit {rc} in {time.time() - started:.0f} s ({self.sha[:12]})")
        return None if killed else rc
