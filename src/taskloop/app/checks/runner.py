"""Checker: one round of checks, from the plan to the CheckRun every reader shares."""
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from taskloop.adapters import check_files, childenv
from taskloop.app.checks import evidence, gateplan
from taskloop.app.checks.attempts import Attempts
from taskloop.app.checks.base import BaseCheck
from taskloop.app.checks.cache import InputKeys, RunMemo
from taskloop.app.checks.executor import CheckExecutor
from taskloop.app.checks.fixer import Fixer
from taskloop.app.checks.host import CheckHost, CheckStuck
from taskloop.app.checks.round import Round
from taskloop.contracts.checks import Check, CheckResult, CheckRun, Durations
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.env import Env
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.plancheck import PlanCheck
from taskloop.contracts.ports import Git
from taskloop.contracts.runkey import BaseSha
from taskloop.domain.checks.durations import merged, seconds
from taskloop.domain.checks.plan import CheckPlan
from taskloop.domain.checks.specs import diff_check, due, gate_items, items_of
from taskloop.domain.checks.writer_split import WriterSplit
from taskloop.stores.api import Doc
from taskloop.stores.bundle import Stores


def cached_gate(cfg: EngineConfig, git: Git, wt: str, stores: Stores, env: Env, bead_env: Mapping[str, str],
                tree: TreeSha, planned: gateplan.PlanDecision | None) -> bool:
    """Read gate evidence without running checks or a plan producer."""
    steps = gate_items(cfg)
    if not tree or not steps:
        return False
    base = git.rev_parse(wt, cfg.base)
    start = git.merge_base(wt, "HEAD", cfg.base) or base
    items = [*([diff_check(start, tree)] if start else []), *steps]
    keys = InputKeys(git, wt, tree)
    engine_env = {**childenv.reaching(childenv.current_env(env)), **bead_env}
    memo = RunMemo(stores, check_files.repo_key(git, wt), keys, BaseSha(base), engine_env)
    changed = git.changed_paths(wt, start, tree) if planned is None and any(c.when for c in items) else []
    return all(memo.has(c) or not due(c, changed, planned.skips if planned is not None else None) for c in items)


class Checker:
    """The round's steps: plan, run, remember (cache, durations), report (log rows, the CheckRun file), and stop a run that keeps
    failing the same way."""

    def __init__(self, host: CheckHost, sleep: Callable[[float], None] = time.sleep) -> None:
        self.host, self.sleep = host, sleep
        self.round = 0
        self.latest: CheckRun | None = None
        self.streak: list[str] = []  # the signatures of the rounds in a row that ended red

    def run(self, stage_checks: Sequence[PlanCheck], name: str, markers: str = "", acceptance_first: bool = False,
            groups: Sequence[str] | None = None,
            conflict_fix: Sequence[str] | None = None, **meta: Any) -> CheckRun:
        """One engine step, no AI: the repo's checks (engine.checks) and the stage's acceptance checks, grouped static, tests,
        acceptance; a red group skips the groups after it. A repo check with `when` runs only when the task changed a matching path;
        `retry` reruns a red one (known flaky). A repo check that passed on the same tree and base is not run again, unless it says
        `"cache": false`; a stage check always runs. The gate is not here: it runs once, on the rebased tree, at land."""
        host = self.host
        host.steps.begin("checks", f"checks: {name}", **meta)
        self.round += 1
        history_doc, history = self._history()
        items = items_of(host.cfg, stage_checks)
        fix_red = Fixer(host).run(CheckPlan.build(items, history, groups, acceptance_first, conflict_fix, markers), self.round)
        # after the fixes: the checks see the fixed files
        tree, base = host.checkout.tree_hash(), host.git.rev_parse(str(host.wt), host.cfg.base)
        plan = CheckPlan.build([*self._diff_check(tree), *items], history, groups, acceptance_first, conflict_fix, markers)
        memo = self._memo(tree, base)
        planned = gateplan.skipped(host, tree, base)
        st = self._executor(memo, history, base_run=True, fix_red=fix_red, planned=planned).run_group(plan, self.round)
        run = self._finish(st, tree, history, history_doc)
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
        history_doc, history = self._history()
        tree, base = host.checkout.tree_hash(), host.git.rev_parse(str(host.wt), host.cfg.base)
        plan = CheckPlan.build([*self._diff_check(tree), *items], history)
        memo = self._memo(tree, base)
        planned = gateplan.skipped(host, tree, base) if not everything else None
        st = self._executor(memo, history, base_run=False, everything=everything, planned=planned).run_group(plan, self.round)
        if learn and st.timings:
            history_doc.write(merged(history, st.timings))
        results = st.results if show_clean else self._quiet(st.results)
        host.detail(evidence.round_lines(results))
        hits = sum(1 for c in results if c.cached)
        return CheckRun(round=st.n, tree=tree, results=results, hits=hits, misses=len(results) - hits)

    def gate_green(self) -> bool:
        """Every gate step's run is in the memo already (the key it would have: tree or inputs, base, env), or the step is not due."""
        host = self.host
        steps, tree = gate_items(host.cfg), host.checkout.tree_hash()
        if not tree or not steps:
            return False
        base = host.git.rev_parse(str(host.wt), host.cfg.base)
        planned = gateplan.skipped(host, tree, base)
        return cached_gate(host.cfg, host.git, str(host.wt), host.stores, host.env, host.bead_env, tree, planned)

    def _history(self) -> tuple[Doc[Durations], Durations]:
        host = self.host
        doc = host.stores.durations.of(check_files.repo_key(host.git, str(host.wt)))
        return doc, doc.get() or Durations()

    def _memo(self, tree: TreeSha, base: str) -> RunMemo:
        """The result store of this repo for this tree and base: the one place a round, `tl check` and the gate's question get theirs.
        The env it keys on is what the engine hands every child: the slot's, and the registered names that reach it."""
        host = self.host
        keys = InputKeys(host.git, host.wt, tree)
        engine_env = {**childenv.reaching(childenv.current_env(host.env)), **host.bead_env}
        repo = check_files.repo_key(host.git, str(host.wt))
        return RunMemo(host.stores, repo, keys, BaseSha(base), engine_env, host.run_id)

    def _executor(self, memo: RunMemo, history: Durations, base_run: bool, fix_red: dict[str, CheckResult] | None = None,
                  everything: bool = False, planned: gateplan.PlanDecision | None = None) -> CheckExecutor:
        host = self.host
        attempts = Attempts(host, BaseCheck(host, memo, base_run), self.sleep)
        return CheckExecutor(host, memo, attempts, host.checklog, history, fix_red, everything, planned)

    def _diff_check(self, tree: str) -> list[Check]:
        """The built-in `git diff --check` over the diff from the merge-base with the base to the tree (untracked files included; none
        when the base does not resolve)."""
        host = self.host
        wt = str(host.wt)
        base = host.git.merge_base(wt, "HEAD", host.cfg.base) or host.git.rev_parse(wt, host.cfg.base)
        return [diff_check(base, tree)] if base and tree else []

    @staticmethod
    def _quiet(results: list[CheckResult]) -> list[CheckResult]:
        """A clean diff check is not a result anyone reads: it stays in the check log's rows only."""
        return [c for c in results if not ("diff" in c.tags and c.exit == 0)]

    def _finish(self, st: Round, tree: TreeSha, history: Durations, history_doc: Doc[Durations]) -> CheckRun:
        host = self.host
        results = self._quiet(st.results)
        host.detail(evidence.round_lines(results))
        if st.timings:
            history_doc.write(merged(history, st.timings))
        hits = sum(1 for c in results if c.cached)
        run = CheckRun(round=st.n, tree=tree, results=results, hits=hits, misses=len(results) - hits)
        host.stores.check_run(host.run_dir.name, st.n).write(run)
        host.steps.outcome(run.verdict.value, evidence.round_outcome(run))
        self.latest = run
        return run

    def _stuck(self, run: CheckRun) -> None:
        """The same reds with the same output `engine.max_same_red` rounds in a row: more writes will not fix them."""
        k = self.host.cfg.max_same_red
        self.streak = [*self.streak, run.signature()][-max(k, 1):] if run.failed else []
        if k and len(self.streak) >= k and len(set(self.streak)) == 1:
            raise CheckStuck(self.streak[-1], k)

    def seconds(self) -> dict[str, float]:
        """{normalised cmd: seconds}: the longest run that passed, from the repo's duration history."""
        return seconds(self.history())

    def history(self) -> Durations:
        return self.host.stores.durations.of(check_files.repo_key(self.host.git, str(self.host.wt))).get() or Durations()

    def split(self) -> WriterSplit:
        return WriterSplit(self.host.cfg, self.seconds())

    def reds(self) -> list[CheckResult]:
        """The checks the last round found red."""
        return self.latest.failed if self.latest else []
