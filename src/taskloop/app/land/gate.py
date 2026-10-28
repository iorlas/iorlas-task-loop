"""The land gate on the rebased tree. A green gate is remembered in the checks' own cache (check-cache/<bead>.json, `whole`, keyed by tree
and base like any check without inputs): the same tree is not gated twice (a push rejected and tried again, a re-land after the network came
back), and the repo checks the cache already holds green are handed to the gate (TL_CHECKS_GREEN), which skips their part."""
import time
from dataclasses import dataclass
from typing import Any

from taskloop.app.checks.cache import CheckCache
from taskloop.contracts import log as rec
from taskloop.contracts.checks import CacheHit, CheckResult


@dataclass(frozen=True)
class Problem:
    """Why a try of the land did not push: `kind` is gate, conflict or verify; `text` goes to the fix round."""

    kind: str
    text: str


class Gate:
    def __init__(self, host: Any) -> None:
        self.e = host

    def cache(self, tree: str) -> CheckCache:
        e = self.e
        return CheckCache(e.stores.check_cache.of(e.bead), f"{tree} {e.git('rev-parse', e.cfg.base)}")

    def green(self, tree: str) -> bool:
        """The gate already passed on exactly this tree (and base)."""
        return bool(tree) and self.e.cfg.gate_text in self.cache(tree).whole

    def remember(self, tree: str) -> None:
        e = self.e
        cache = self.cache(tree)
        res = CheckResult(id="gate", cmd=e.cfg.gate_text, group="gate", exit=0, status="passed")
        cache.whole[e.cfg.gate_text] = CacheHit(result=res)
        cache.save(e.git("rev-parse", e.cfg.base))

    def run(self) -> Problem | None:
        """-> None when the gate passed (or already had on this tree), else the problem for a fix round."""
        e = self.e
        e.gate_log = e.run_dir / f"gate.r{e.fixes + 1}.log"
        tree = e.git("rev-parse", "HEAD^{tree}")
        started, skipped = time.time(), False
        e.log.emit(rec.GateStart(cmd=e.cfg.gate_text, log=str(e.gate_log), tree=tree))
        if self.green(tree):
            e.log.note(f"gate skipped: `{e.cfg.gate_text[:80]}` already passed on tree {tree[:12]}")
            rc, tail, skipped = 0, "", True
        else:
            rc, tail = self.execute(tree)
        e.log.emit(rec.GateEnd(exit=rc, secs=round(time.time() - started), skipped=skipped))
        if rc < 0 and not e.killed:  # tl-y35: killed by a signal (an operator's SIGTERM, the machine): not the code's fault
            raise e.blocked_for(f"failed: stopped: the gate was killed by signal {-rc}; the bead goes back to open and the next run "
                                "runs the gate again (no fix round, no failure counted)", "PAUSE_KILLED")
        if not rc:
            return None
        e.steps.outcome("gate red", (tail.strip().splitlines() or [""])[-1])
        return Problem("gate", tail)

    def execute(self, tree: str) -> tuple[int, str]:
        e = self.e
        green = e.checker.green_ids(tree)  # repo checks green on this tree's inputs: the gate may skip their part
        rc, tail = e.sh(e.cfg.gate, save=e.gate_log, timeout=float(e.cfg.gate_timeout_min) * 60,
                        env={"TL_CHECKS_GREEN": ",".join(green)} if green else None)
        if rc == 0:
            self.remember(tree)
        return rc, tail
