"""Checker: one round of checks, from the plan to the CheckRun every reader shares."""
import time
from collections.abc import Callable, Sequence

from tlkernel import check_files
from tlkernel.checks import Check, CheckResult, CheckRun, Durations
from tlkernel.config import EngineConfig
from tlkernel.env import Env
from tlkernel.gitport import GateGit
from tlkernel.ids import TreeSha
from tlkernel.plancheck import PlanCheck
from tlkernel.runkey import BaseSha
from tlkernel.storeapi import Doc

from tlgate import evidence, gateplan
from tlgate.attempts import Attempts
from tlgate.base import BaseCheck
from tlgate.cache import InputKeys, RunnerMemo
from tlgate.clean import guard_slot, isolated
from tlgate.domain.durations import merged, seconds
from tlgate.domain.plan import CheckPlan
from tlgate.domain.specs import diff_check, due, engine_digest, gate_items, items_of, repo_check
from tlgate.domain.writer_split import WriterSplit
from tlgate.execution import keyed_env
from tlgate.executor import CheckExecutor
from tlgate.fixer import Fixer
from tlgate.host import CheckFault, CheckHost, CheckStuck
from tlgate.ports import GateStores
from tlgate.round import Round


def cached_gate(cfg: EngineConfig, git: GateGit, wt: str, stores: GateStores, env: Env,
                tree: TreeSha, planned: gateplan.PlanDecision | None, *, clean: bool = False,
                slot_wt: str | None = None) -> bool:
    """Read gate evidence without running checks or a plan producer."""
    clean = clean and cfg.gate_tree == "clean"  # gate_tree slot: the gate's passes are the slot's own
    steps = gate_items(cfg)
    if not tree or not steps:
        return False
    base = git.rev_parse(wt, cfg.base)
    start = git.merge_base(wt, "HEAD", cfg.base) or base
    items = [*([diff_check(start, tree)] if start else []), *steps]
    keys = InputKeys(git, wt, tree, clean=clean, pins=cfg.pin_files)
    memo = RunnerMemo(stores, check_files.repo_key(git, wt), keys, BaseSha(base), keyed_env(env), executor=cfg.executor.host)
    if clean or slot_wt is not None:
        memo.slot_keys = InputKeys(git, slot_wt or wt, tree, pins=cfg.pin_files)
    memo.checks = {c.id: repo_check(c, cfg) for c in cfg.checks}
    memo.checks.update({c.id: c for c in steps})
    changed = git.changed_paths(wt, start, tree, required=True) if planned is None and any(c.when for c in items) else []
    return all(memo.has(c) or not due(c, changed, planned.skips if planned is not None else None) for c in items)


class Checker:
    """The round's steps: plan, run, remember (cache, durations), report (log rows, the CheckRun file), and stop a run that keeps
    failing the same way."""

    def __init__(self, host: CheckHost, sleep: Callable[[float], None] = time.sleep, *, clean: bool = False,
                 slot_host: CheckHost | None = None) -> None:
        self.host, self.sleep = host, sleep
        self.clean = clean
        self.slot_host = slot_host
        self.round = 0
        self.latest: CheckRun | None = None
        self.streak: list[str] = []  # the signatures of the rounds in a row that ended red

    def run(self, stage_checks: Sequence[PlanCheck], name: str, markers: str = "", acceptance_first: bool = False,
            groups: Sequence[str] | None = None,
            conflict_fix: Sequence[str] | None = None, **meta: object) -> CheckRun:
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

    def run_items(self, items: Sequence[Check], everything: bool = False, learn: bool = True, show_clean: bool = False,
                  clean: bool = False, all_files: bool = False) -> CheckRun:
        """The registry's checks (the gate's steps, or the ones `tl check` names) as one block, through the same planner, executor
        and cache as a stage's round: groups in order, a red group skips the groups after it, a step green at its inputs is cached.
        A clean diff check is left out of the result (show_clean keeps it: `tl check` prints a line for it). No fix commands and no
        base run (the tree is the rebased one: a red is red). everything: `when` is ignored.
        all_files: pass_files checks get every tracked file. learn: the durations of what passed are
        remembered. clean: judge committed HEAD, routing run_in=slot to the guarded slot and other checks to a fresh checkout.
        The rows are the check log's (start and end per step); no step book, no streak."""
        if clean and self.host.cfg.gate_tree == "slot":
            guard_slot(self.host)  # the gate runs here: the slot's passes (fix rounds too) are the gate's
            clean = False
        if clean:
            with isolated(self.host) as clean_host:
                checker = Checker(clean_host, self.sleep, clean=True, slot_host=self.host)
                checker.round = self.round
                run = checker.run_items(items, everything, learn, show_clean, all_files=all_files)
                self.round = checker.round
                return run
        host = self.host
        self.round += 1
        history_doc, history = self._history()
        tree, base = host.checkout.tree_hash(), host.git.rev_parse(str(host.wt), host.cfg.base)
        config = engine_digest(host.cfg)
        plan = CheckPlan.build([*self._diff_check(tree), *items], history)
        memo = self._memo(tree, base)
        planned = gateplan.skipped(host, tree, base) if not everything else None
        st = self._executor(memo, history, base_run=False, everything=everything, planned=planned,
                            all_files=all_files).run_group(plan, self.round)
        if learn and st.timings:
            history_doc.write(merged(history, st.timings))
        results = st.results if show_clean else self._quiet(st.results)
        host.detail(evidence.round_lines(results))
        hits = sum(1 for c in results if c.cached)
        return CheckRun(round=st.n, tree=tree, base=BaseSha(base), config=config, results=results, hits=hits, misses=len(results) - hits)

    def gate_green(self, clean: bool = False) -> bool:
        """Every gate step's run is in the memo already (the key it would have: tree or inputs, base, env), or the step is not due."""
        clean = clean and self.host.cfg.gate_tree == "clean"
        if clean:
            try:
                with isolated(self.host) as clean_host:
                    return Checker(clean_host, self.sleep, clean=True, slot_host=self.host).gate_green()
            except CheckFault:
                return False
        host = self.host
        steps, tree = gate_items(host.cfg), host.checkout.tree_hash()
        if not tree or not steps:
            return False
        base = host.git.rev_parse(str(host.wt), host.cfg.base)
        planned = gateplan.skipped(host, tree, base)
        return cached_gate(host.cfg, host.git, str(host.wt), host.stores, host.env, tree, planned,
                           clean=self.clean, slot_wt=str(self.slot_host.wt) if self.slot_host is not None else None)

    def _history(self) -> tuple[Doc[Durations], Durations]:
        host = self.host
        doc = host.stores.durations.of(check_files.repo_key(host.git, str(host.wt)))
        return doc, doc.get() or Durations()

    def _memo(self, tree: TreeSha, base: str) -> RunnerMemo:
        """The result store of this repo for this tree and base: the one place a round, `tl check` and the gate's question get theirs.
        Slot names and state paths do not distinguish receipts; each check's declared env still does."""
        host = self.host
        keys = InputKeys(host.git, host.wt, tree, clean=self.clean, pins=host.cfg.pin_files)
        repo = check_files.repo_key(host.git, str(host.wt))
        memo = RunnerMemo(host.stores, repo, keys, BaseSha(base), keyed_env(host.env), host.run_id, executor=host.cfg.executor.host)
        if self.slot_host is not None:
            # The mixed plan shares receipts, but slot requirements use a non-clean checker's ignored-input digests.
            slot_checker = Checker(self.slot_host, self.sleep, clean=False)
            memo.slot_keys = slot_checker._memo(tree, base).keys
        return memo

    def _executor(self, memo: RunnerMemo, history: Durations, base_run: bool, fix_red: dict[str, CheckResult] | None = None,
                  everything: bool = False, planned: gateplan.PlanDecision | None = None,
                  all_files: bool = False) -> CheckExecutor:
        host = self.host
        attempts = Attempts(host, BaseCheck(host, memo, base_run), self.sleep)
        executor = CheckExecutor(host, memo, attempts, host.checklog, history, fix_red, everything, planned, all_files)
        if self.slot_host is not None:
            slot = self.slot_host
            slot_attempts = Attempts(slot, BaseCheck(slot, memo, base_run), self.sleep)
            executor.slot = CheckExecutor(slot, memo, slot_attempts, slot.checklog, history, fix_red, everything, planned, all_files)
        return executor

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
