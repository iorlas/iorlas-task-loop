"""CheckExecutor: run the steps of a round in order, deciding for each whether it runs, is skipped, is answered by an earlier
run, or is answered by the cache."""
import time
from pathlib import Path

from taskloop.adapters import check_files
from taskloop.app.checks.attempts import Attempts, Outcome
from taskloop.app.checks.cache import RunMemo
from taskloop.app.checks.checklog import CheckLog
from taskloop.app.checks.gateplan import PlanDecision
from taskloop.app.checks.host import CheckFault, CheckHost
from taskloop.app.checks.lanes import Lanes
from taskloop.app.checks.resources import LeaseCancelled, Resources
from taskloop.app.checks.round import Round
from taskloop.contracts.checks import UNVERIFIED_EXIT, Check, CheckFaultKind, CheckResult, Duration, Durations, verdict_of
from taskloop.contracts.runkey import RunKey
from taskloop.domain.checks.durations import CHEAP_S, expected_secs
from taskloop.domain.checks.inputs import touched
from taskloop.domain.checks.matchers import cs_error_lines, diff_check_text, output_signature, safe_name, stale_tree
from taskloop.domain.checks.names import log_var, rc_var
from taskloop.domain.checks.plan import CheckPlan, Step
from taskloop.domain.checks.specs import due

PROJECT_LOG = "client/Logs/unity-project-files.log"  # where Unity says why the project files could not be regenerated
PROJECT_LOG_LINES = 20
FAILED_FIRST = " failed first"


class CheckExecutor:
    def __init__(self, host: CheckHost, memo: RunMemo, attempts: Attempts, checklog: CheckLog,
                 history: Durations, fix_red: dict[str, CheckResult] | None = None, everything: bool = False,
                 planned: PlanDecision | None = None) -> None:
        self.host, self.memo, self.attempts, self.checklog, self.history = host, memo, attempts, checklog, history
        self.everything = everything  # `when` is ignored: every check is due (tl check --all)
        self.planned = planned
        self.gates = {k.id for k in host.cfg.gate_checks}
        self.fix_red = fix_red or {}  # id -> the red of a check whose fix command failed: it does not run
        self.logs = host.run_dir / "checks"
        self.resources = Resources(host)
        self.began = time.time()  # the block's start: where a check's `at` counts from

    def run_group(self, plan: CheckPlan, rnd: int) -> Round:
        """Run every step of the plan, in order, as one block (the cheap checks first, the Unity group last)."""
        st = Round(rnd, results=list(plan.skipped))
        self.logs.mkdir(exist_ok=True)
        self.began = time.time()
        lanes = plan.lanes()
        if len(lanes) > 1:  # lanes run at the same time; the first red cancels the rest
            st = Lanes(self.host, self.step, self.drop).run(plan, lanes, st)
        else:
            for n, step in enumerate(plan.steps):
                self.step(step, n, st)
        if (self.planned is None or self.planned.output) and not any(r.red or r.cancelled for r in st.results):
            for n, res in st.by_step.items():
                if res.status == "skipped" and res.planned:
                    check = plan.steps[n].check
                    decision = self.planned if check.id in self.gates else None
                    key = (self.memo.planned_key(check, decision.command, decision.output) if decision is not None
                           else self.memo.planned_key(check))
                    self.memo.remember(key, res, st.n, "")
        return st

    def step(self, step: Step, n: int, st: Round) -> None:
        """One step: decided, run if it must, recorded."""
        res, cid = self._decide(step, n, st)
        st.results.append(res)
        st.by_step[n] = res
        self.checklog.close(step.check, res, cid, st.n)

    def drop(self, step: Step, n: int, st: Round, red: str) -> None:
        """A step its lane never began because another lane went red first."""
        res = CheckResult.cancelled_by(step.check, red, at=round(time.time() - self.began, 1))
        st.results.append(res)
        st.by_step[n] = res
        self.checklog.close(step.check, res, None, st.n)

    def _decide(self, step: Step, n: int, st: Round) -> tuple[CheckResult, str | None]:
        c = step.check
        skipped = self._skip(step, st)
        if skipped:
            if skipped.why.endswith(FAILED_FIRST):
                st.red_skipped.add(n)
            return skipped, None
        if c.id in self.fix_red:
            st.red = c.group
            return self.fix_red[c.id], None
        again = self._reused(c, st)
        if again:
            st.red = c.group if again.exit != 0 else st.red
            key = self._key(c) if c.cache else None
            if key is not None:  # the same command on the same tree: this check's run is as much a fact as the first one's
                self.memo.remember(key, again, st.n, "")
            return again, None
        key = self._key(c)
        hit = self.memo.hit(key)
        cid, name = None, self._log_name(n, c, st.n)
        if hit is not None:
            self.memo.reuse(hit)
            res, where = self.memo.cached(c, hit).replace(lane=c.lane), hit.log_abs
            if res.note:
                self.host.log.note(f"cached: {c.id}, {res.note}")
        elif self.resources.lacking(c):
            return self._deferred(c, st), None
        else:
            cid = self.checklog.start(c, st.n, "checks/" + name)
            res, where = self._launch(step, st, name, key), str(self.logs / name)
            if res.cancelled:  # another lane's red stopped it: no verdict, nothing to remember, no red of its own
                return res, cid
        self.memo.ran[self.memo.command_key(c)] = (res, c.wall_min)
        self._publish(c, res, where, st)
        if res.exit != 0 and not res.base_red:
            st.red = c.group
        return res, cid

    def _deferred(self, c: Check, st: Round) -> CheckResult:
        """The check needs a resource this host lacks: it is not run, and not a failure (unverified). Whether the land may go on past it
        is the diff's: if nothing it reads changed, a host that has the resource has nothing new to verify."""
        lack = self.resources.lacking(c)
        st.changed = self.host.checkout.changed_paths() if st.changed is None else st.changed
        changed = touched(c, st.changed)
        said = "its inputs changed: it waits for a host that has it" if changed else "its inputs are unchanged: the land may go on"
        why = f"deferred: needs {', '.join(lack)}, which this host does not have; {said}"
        self.host.log.note(f"`{c.id}` {why}")
        return CheckResult(id=c.id, cmd=c.cmd, group=c.group, exit=UNVERIFIED_EXIT, status="unverified", why=why, deferred=lack,
                           inputs_changed=changed, tags=list(c.tags), lane=c.lane)

    @staticmethod
    def _log_name(n: int, c: Check, rnd: int) -> str:
        return f"{n:02d}-{safe_name(c.id)}.r{rnd}.log"

    def _skip(self, step: Step, st: Round) -> CheckResult | None:
        c = step.check
        gone = self._producer_gone(step, st)
        if gone:
            return CheckResult.skipped(c, f"producer {gone} did not run", producer=gone)
        if st.red and (c.group != st.red or expected_secs(c.cmd, self.history) >= CHEAP_S or step.unity
                       or any(d in st.red_skipped for d in step.env)):
            # a red group skips the groups after it, and any red skips every expensive check (the cheap ones of its own group run to
            # the end, so the writer sees all the cheap failures at once; the Unity group never runs after a red)
            return CheckResult.skipped(c, st.red + FAILED_FIRST)
        if not self.everything and c.id not in self.fix_red:
            decision = self.planned
            planned = decision.skips if decision is not None and (c.id in self.gates or not decision.output) else None
            if planned is None and c.when and st.changed is None:
                st.changed = self.host.checkout.changed_paths()
            if not due(c, st.changed or [], planned):
                why = planned[c.id] if planned is not None else "no change under " + ", ".join(c.when)
                return CheckResult.skipped(c, why).replace(planned=True)
        return None

    @staticmethod
    def _producer_gone(step: Step, st: Round) -> str:
        """The id of a check this one reads (Check.reads) that did not run, or ran red, or is not in this round: it has nothing to read,
        and no write can change that. Such a check is skipped, never failed: the graph skips its readers."""
        if step.absent:
            return step.absent[0]
        for p in step.env:
            res = st.by_step.get(p)
            if res is None or res.exit != 0 or rc_var(res.id) not in st.env:
                return res.id if res else "?"
        return ""

    def _reused(self, c: Check, st: Round) -> CheckResult | None:
        """Each distinct command runs once per block, whatever limit its copy carries; the limit matters only when the first run
        timed out under a shorter one."""
        before = self.memo.ran.get(self.memo.command_key(c))
        if before is None or (before[0].exit == 124 and before[1] < c.wall_min):
            return None
        self.host.log.note(f"`{c.cmd[:120]}` already ran in this block: its result is reused")
        return before[0].replace(id=c.id, cmd=c.cmd, group=c.group, cached=False, reused=True, log="", waited=0.0,
                                lane=c.lane)

    def _key(self, c: Check) -> RunKey | None:
        """The memo key of this run, None when it may not be cached. A glob that selects nothing would cache a green over changed
        code: said, and no key."""
        if c.cache and c.inputs:
            for g in self.memo.keys.dead(c):
                self.host.warn(f"inputs glob {g} matches no tracked file; not cached")
        return self.memo.key(c)

    def _publish(self, c: Check, res: CheckResult, log_abs: str, st: Round) -> None:
        """Later checks read this one's log and exit code: $TL_CHECK_LOG_<ID>, $TL_CHECK_RC_<ID>."""
        if c.group != "acceptance" and res.exit is not None and Path(log_abs).is_file():
            st.env[log_var(c.id)], st.env[rc_var(c.id)] = log_abs, str(res.exit)

    def _launch(self, step: Step, st: Round, name: str, key: RunKey | None) -> CheckResult:
        c = step.check
        t0 = time.time()
        try:
            with self.resources.hold(c, st.cancel) as lease:
                t0 = time.time()  # the wait for a lease is not the check's time
                out = self.attempts.run(c, self.logs / name, st.env, st.cancel)
                took = round(time.time() - t0)
        except LeaseCancelled:
            return CheckResult.cancelled_by(c, st.cancel.red if st.cancel else "", at=round(t0 - self.began, 1))
        if out.stopped:  # the lease is back already: the block above ended
            return CheckResult.cancelled_by(c, st.cancel.red if st.cancel else "", "checks/" + name, round(t0 - self.began, 1), took)
        self._fault(c, out, st)
        res = self._result(c, out, name, took).replace(waited=round(lease.waited, 1), lane=c.lane, at=round(t0 - self.began, 1))
        if out.rc == 0:  # only a green run says what the check costs: a red one stops early
            st.timings.append(Duration(t=time.time(), run_id=self.host.run_id, bead=self.host.bead, call_id=c.id, step=c.cmd,
                                       tree=key.tree if key else "", base=key.base if key else "",
                                       exec_seconds=time.time() - t0, wait_seconds=round(lease.waited, 1)))
            if key is not None:
                self.memo.remember(key, res, st.n, str(self.logs / name))
        return res

    def _fault(self, c: Check, out: Outcome, st: Round) -> None:
        """Two reds that are not the code's: a tree older than the config it runs, and a check killed by a signal."""
        stale = stale_tree(out.seen or out.tail) if out.rc and c.repo else ""
        if stale:
            raise CheckFault(CheckFaultKind.STALE_BASE, f"failed: infrastructure: the configured check `{c.id}` needs something this tree "
                             f"lacks (\"{stale}\"): the tree is older than the base's .task-loop.json, which no writer can fix", out.rc)
        if out.rc < 0 and not self.host.killed:
            raise CheckFault(CheckFaultKind.KILLED, f"failed: stopped: check `{c.id}` was killed by signal {-out.rc}; the bead goes "
                             "back to open and the next run runs it again (no fix round, no failure counted)", out.rc)

    def _result(self, c: Check, out: Outcome, name: str, secs: int) -> CheckResult:
        tail = diff_check_text(out.seen) if "diff" in c.tags and out.rc else out.tail[-1500:]  # the writer's text; the log keeps all
        if out.rc and not out.base_red:
            tail += self._project_log(c, out.seen, self.logs / name)
        return CheckResult(id=c.id, cmd=c.cmd, group=c.group, exit=out.rc, status=verdict_of(out.rc), tries=out.tries,
                           tail=tail, secs=secs, log="checks/" + name, base_red=out.base_red, wall_hit=out.wall_hit, wall_min=c.wall_min,
                           sig=output_signature(out.seen) if out.rc else "", tags=list(c.tags))

    def _project_log(self, c: Check, seen: str, log: Path) -> str:
        """A red analyzer whose output shows no compile error because the project files could not be regenerated: the first
        PROJECT_LOG_LINES error lines of the log Unity wrote for that, in the output the writer sees (and in the saved log)."""
        path = c.tail_log or (PROJECT_LOG if "analy" in (c.id + " " + c.cmd).lower() else "")
        if not path or cs_error_lines(seen, 1):
            return ""
        lines = cs_error_lines("\n".join(check_files.read_lines(Path(self.host.wt) / path)), PROJECT_LOG_LINES)
        if not lines:
            return ""
        block = (f"\n(the first {len(lines)} compile errors of {path}, where the project files could not be regenerated)\n"
                 + "\n".join(lines))
        with open(log, "a", encoding="utf-8") as f:
            f.write(block)
        return block
