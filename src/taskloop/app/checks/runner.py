"""Checker: one round of checks, from the plan to the CheckRun every reader shares."""
import os
import time
from collections.abc import Callable, Sequence
from typing import Any

from taskloop.adapters import check_files
from taskloop.app.checks import evidence
from taskloop.app.checks.attempts import Attempts
from taskloop.app.checks.base import BaseCheck
from taskloop.app.checks.cache import CheckCache, InputKeys
from taskloop.app.checks.executor import CheckExecutor, Round
from taskloop.app.checks.host import CheckHost, CheckStuck
from taskloop.contracts.checks import CheckResult, CheckRun, Durations
from taskloop.domain.checks.durations import merged, seconds
from taskloop.domain.checks.plan import CheckPlan
from taskloop.domain.checks.specs import items_of, repo_check
from taskloop.domain.checks.writer_split import WriterSplit


class Checker:
    """The round's steps: plan, run, remember (cache, durations), report (log rows, the CheckRun file), and stop a run that keeps
    failing the same way."""

    def __init__(self, host: CheckHost, sleep: Callable[[float], None] = time.sleep) -> None:
        self.host, self.sleep = host, sleep
        self.round = 0
        self.latest: CheckRun | None = None
        self.streak: list[str] = []  # the signatures of the rounds in a row that ended red
        self.last_red: dict[str, tuple[str, float]] = {}  # check id -> (its red output's signature, secs) from its last red

    def run(self, stage_checks: Sequence[str], name: str, markers: str = "", acceptance_first: bool = False,
            groups: Sequence[str] | None = None,
            conflict_fix: Sequence[str] | None = None, **meta: Any) -> CheckRun:
        """One engine step, no AI: the repo's checks (engine.checks) and the stage's acceptance checks, grouped static, tests,
        acceptance; a red group skips the groups after it. A repo check with `when` runs only when the task changed a matching path;
        `retry` reruns a red one (known flaky). A repo check that passed on the same tree and base is not run again, unless it says
        `"cache": false`; a stage check always runs. The gate is not here: it runs once, on the rebased tree, at land."""
        host = self.host
        host.steps.begin("checks", f"checks: {name}", **meta)
        self.round += 1
        env = host.git_env()
        history_doc = host.stores.durations.of(check_files.repo_key(str(host.wt), env))
        history = history_doc.read() or Durations()
        plan = CheckPlan.build(items_of(host.cfg, stage_checks), history, lambda p: os.path.exists(os.path.join(host.wt, p)), groups,
                               acceptance_first, conflict_fix, markers)
        tree, base = host.tree_hash(), host.git("rev-parse", host.cfg.base)
        cache = CheckCache(host.stores.check_cache.of(host.bead), f"{tree} {base}")
        keys = InputKeys(host.wt, tree, base, env)
        attempts = Attempts(host, BaseCheck(host, cache, base, host.git_env), self.last_red, self.sleep)
        st = CheckExecutor(host, cache, keys, attempts, host.checklog, history).run_group(plan, self.round)
        run = self._finish(st, tree, history, history_doc)
        cache.save(base)
        host.checklog.round(host.steps.id, run)
        self._remember_reds(run)
        self._stuck(run)
        return run

    def _finish(self, st: Round, tree: str, history: Durations, history_doc: Any) -> CheckRun:
        host = self.host
        host.detail(evidence.round_lines(st.results))
        if st.timings:
            history_doc.write(merged(history, st.timings))
        hits = sum(1 for c in st.results if c.cached)
        run = CheckRun(round=st.n, tree=tree, results=st.results, hits=hits, misses=len(st.results) - hits)
        host.stores.check_run(host.run_dir.name, st.n).write(run)
        bad, hung = run.failed, [c for c in run.failed if c.hung]
        host.steps.outcome("red" if bad else "green", evidence.round_outcome(run, hung))
        self.latest = run
        return run

    def _remember_reds(self, run: CheckRun) -> None:
        for c in run.results:
            if c.exit is None or c.cached:
                continue
            if c.red:
                self.last_red[c.id] = (c.sig, c.secs)
            else:
                self.last_red.pop(c.id, None)

    def _stuck(self, run: CheckRun) -> None:
        """The same reds with the same output `engine.max_same_red` rounds in a row: more writes will not fix them."""
        k = int(self.host.cfg.max_same_red)
        self.streak = [*self.streak, run.signature()][-max(k, 1):] if run.failed else []
        if k and len(self.streak) >= k and len(set(self.streak)) == 1:
            raise CheckStuck(self.streak[-1], k)

    def seconds(self) -> dict[str, float]:
        """{normalised cmd: seconds}: the longest run that passed, from the repo's duration history."""
        return seconds(self.history())

    def history(self) -> Durations:
        return self.host.stores.durations.of(check_files.repo_key(str(self.host.wt), self.host.git_env())).read() or Durations()

    def split(self) -> WriterSplit:
        return WriterSplit(self.host.cfg, self.seconds())

    def reds(self) -> list[CheckResult]:
        """The checks the last round found red."""
        return self.latest.failed if self.latest else []

    def green_ids(self, tree: str) -> list[str]:
        """Ids of the repo checks with a green result on this tree: by their inputs hash, else by tree and base."""
        host = self.host
        base = host.git("rev-parse", host.cfg.base)
        cache = CheckCache(host.stores.check_cache.of(host.bead), f"{tree} {base}")
        return cache.green_ids([repo_check(k, host.cfg) for k in host.cfg.checks], InputKeys(host.wt, tree, base, host.git_env()))
