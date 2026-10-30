"""Checker: one round of checks, from the plan to the CheckRun every reader shares."""
import time
from collections.abc import Callable, Sequence
from typing import Any

from taskloop.adapters import check_files
from taskloop.app.checks import evidence
from taskloop.app.checks.attempts import Attempts
from taskloop.app.checks.base import BaseCheck
from taskloop.app.checks.cache import CheckCache, InputKeys
from taskloop.app.checks.executor import CheckExecutor, Round
from taskloop.app.checks.fixer import Fixer
from taskloop.app.checks.host import CheckHost, CheckStuck
from taskloop.contracts.checks import Check, CheckResult, CheckRun, Durations
from taskloop.contracts.ids import TreeSha
from taskloop.domain.checks.durations import merged, seconds
from taskloop.domain.checks.plan import CheckPlan
from taskloop.domain.checks.specs import DIFF_CHECK, diff_check, due, gate_items, items_of
from taskloop.domain.checks.writer_split import WriterSplit


class Checker:
    """The round's steps: plan, run, remember (cache, durations), report (log rows, the CheckRun file), and stop a run that keeps
    failing the same way."""

    def __init__(self, host: CheckHost, sleep: Callable[[float], None] = time.sleep) -> None:
        self.host, self.sleep = host, sleep
        self.round = 0
        self.latest: CheckRun | None = None
        self.streak: list[str] = []  # the signatures of the rounds in a row that ended red

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
        env = host.checkout.git_env()
        history_doc = host.stores.durations.of(check_files.repo_key(str(host.wt), env))
        history = history_doc.read() or Durations()
        items = items_of(host.cfg, stage_checks)
        fix_red = Fixer(host).run(CheckPlan.build(items, history, groups, acceptance_first, conflict_fix, markers), self.round)
        tree, base = host.checkout.tree_hash(), host.git("rev-parse", host.cfg.base)  # after the fixes: the checks see the fixed files
        plan = CheckPlan.build([*self._diff_check(tree), *items], history, groups, acceptance_first, conflict_fix, markers)
        cache = CheckCache(host.stores.check_cache.of(host.bead), f"{tree} {base}")
        keys = InputKeys(host.wt, tree, base, env)
        attempts = Attempts(host, BaseCheck(host, cache, base, host.checkout.git_env), self.sleep)
        st = CheckExecutor(host, cache, keys, attempts, host.checklog, history, fix_red).run_group(plan, self.round)
        run = self._finish(st, tree, history, history_doc)
        cache.save(base)
        host.checklog.round(host.steps.id, run)
        self._stuck(run)
        return run

    def run_items(self, items: Sequence[Check], everything: bool = False, learn: bool = True, show_clean: bool = False) -> CheckRun:
        """The registry's checks (the gate's steps, or the ones `tl check` names) as one block, through the same planner, executor
        and cache as a stage's round: groups in order, a red group skips the groups after it, a step green at its inputs is cached.
        A clean diff check is left out of the result (show_clean keeps it: `tl check` prints a line for it). No fix commands and no
        base run (the tree is the rebased one: a red is red). everything: `when` is ignored. learn: the durations of what passed are
        remembered. The rows are the check log's (start and end per step); no step book, no streak."""
        host = self.host
        self.round += 1
        env = host.checkout.git_env()
        history_doc = host.stores.durations.of(check_files.repo_key(str(host.wt), env))
        history = history_doc.read() or Durations()
        tree, base = host.checkout.tree_hash(), host.git("rev-parse", host.cfg.base)
        plan = CheckPlan.build([*self._diff_check(tree), *items], history)
        cache = CheckCache(host.stores.check_cache.of(host.bead), f"{tree} {base}")
        keys = InputKeys(host.wt, tree, base, env)
        attempts = Attempts(host, BaseCheck(host, cache, "", host.checkout.git_env), self.sleep)  # no sha: no base run
        st = CheckExecutor(host, cache, keys, attempts, host.checklog, history, everything=everything).run_group(plan, self.round)
        if learn and st.timings:
            history_doc.write(merged(history, st.timings))
        cache.save(base)
        results = st.results if show_clean else self._quiet(st.results)
        host.detail(evidence.round_lines(results))
        hits = sum(1 for c in results if c.cached)
        return CheckRun(round=st.n, tree=tree, results=results, hits=hits, misses=len(results) - hits)

    def gate_green(self) -> bool:
        """Every gate step is green on this tree and base already (by its inputs, else by tree and base), or not due (`when`)."""
        host = self.host
        steps, tree = gate_items(host.cfg), host.checkout.tree_hash()
        if not tree or not steps:
            return False
        items = [*self._diff_check(tree), *steps]
        base = host.git("rev-parse", host.cfg.base)
        cache = CheckCache(host.stores.check_cache.of(host.bead), f"{tree} {base}")
        green = cache.green_ids(items, InputKeys(host.wt, tree, base, host.checkout.git_env()))
        changed = host.checkout.changed_paths() if any(c.when for c in items) else []
        return all(c.id in green or not due(c, changed) for c in items)

    def _diff_check(self, tree: str) -> list[Check]:
        """The built-in `git diff --check` over the diff from the merge-base with the base to the tree (untracked files included; none
        when the base does not resolve)."""
        host = self.host
        base = host.git("merge-base", "HEAD", host.cfg.base) or host.git("rev-parse", host.cfg.base)
        return [diff_check(base, tree)] if base and tree else []

    @staticmethod
    def _quiet(results: list[CheckResult]) -> list[CheckResult]:
        """A clean diff check is not a result anyone reads: it stays in the check log's rows only."""
        return [c for c in results if not (c.id == DIFF_CHECK and c.exit == 0)]

    def _finish(self, st: Round, tree: TreeSha, history: Durations, history_doc: Any) -> CheckRun:
        host = self.host
        results = self._quiet(st.results)
        host.detail(evidence.round_lines(results))
        if st.timings:
            history_doc.write(merged(history, st.timings))
        hits = sum(1 for c in results if c.cached)
        run = CheckRun(round=st.n, tree=tree, results=results, hits=hits, misses=len(results) - hits)
        host.stores.check_run(host.run_dir.name, st.n).write(run)
        host.steps.outcome("red" if run.failed else "unverified" if run.unverified else "green", evidence.round_outcome(run))
        self.latest = run
        return run

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
        return self.host.stores.durations.of(check_files.repo_key(str(self.host.wt), self.host.checkout.git_env())).read() or Durations()

    def split(self) -> WriterSplit:
        return WriterSplit(self.host.cfg, self.seconds())

    def reds(self) -> list[CheckResult]:
        """The checks the last round found red."""
        return self.latest.failed if self.latest else []
