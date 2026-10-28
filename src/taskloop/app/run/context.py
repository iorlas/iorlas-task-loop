"""RunContext: the identity of one engine run and the objects it writes through. Built once at the start of the run."""
import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

from taskloop.app.run import console
from taskloop.app.run.budget import Budget
from taskloop.app.run.calls import Calls
from taskloop.app.run.checklog import CheckLog
from taskloop.app.run.steps import Steps
from taskloop.contracts.config import EngineConfig
from taskloop.stores.bundle import Stores
from taskloop.stores.runlog import RunLog


@dataclasses.dataclass
class RunContext:
    bead: str
    cfg: EngineConfig
    wt: Path
    run: str  # <bead>-<YYYYMMDD-HHMMSS>: the stem of the run's files
    run_dir: Path
    log: RunLog
    steps: Steps
    budget: Budget
    calls: Calls
    checklog: CheckLog
    store: Any  # the bead store (show, comments, bd)
    route: Any  # the delegate (resolve, runner)
    clock: Any  # now, monotonic
    traces: Any  # the TraceStore: one RunTrace per finished run
    dry: bool = False

    @classmethod
    def open(cls, bead: str, cfg: EngineConfig, wt: Path, run: str, run_dir: Path, stores: Stores, store: Any, route: Any, clock: Any,
             sessions: list[dict[str, Any]], stats: dict[str, int], opencode: Callable[[str], str], context_tokens: Callable[[str], int | None],
             echo: Callable[[str], None], verbose: bool = True, dry: bool = False, now: Callable[[], float] | None = None,
             guard: Callable[[str], None] | None = None, on_step: Callable[[str], None] | None = None) -> "RunContext":
        """The context of run `run`: its log (appending to the file it may already have: ids go on), steps, budget, calls and checks."""
        now = now or clock.now
        seen = stores.run_log(run).read_from()
        log = RunLog(stores.run_log(run), echo, console.QUIET, console.line(verbose), now, len(seen.items) + seen.skipped)
        steps = Steps(log, now, guard, on_step)
        return cls(bead, cfg, wt, run, run_dir, log, steps, Budget(cfg, now), Calls(log, lambda: steps.cur.n if steps.cur else None, sessions, stats,
                   opencode, context_tokens), CheckLog(log), store, route, clock, stores.traces, dry)
