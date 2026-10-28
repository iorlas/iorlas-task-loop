"""CheckExecutor: run the steps of a round in order, deciding for each whether it runs, is skipped, is answered by an earlier
run, or is answered by the cache."""
import dataclasses
import fnmatch
import time
from dataclasses import dataclass, field
from pathlib import Path

from taskloop.adapters import check_files
from taskloop.app.checks.attempts import Attempts, Outcome
from taskloop.app.checks.cache import CheckCache, InputKeys
from taskloop.app.checks.checklog import CheckLog
from taskloop.app.checks.host import CheckFault, CheckHost
from taskloop.contracts.checks import Check, CheckFaultKind, CheckResult, Durations
from taskloop.domain.checks.durations import CHEAP_S, expected_secs
from taskloop.domain.checks.matchers import cs_error_lines, output_signature, safe_name, stale_tree
from taskloop.domain.checks.names import log_var, norm, rc_var
from taskloop.domain.checks.plan import CheckPlan, Step

PROJECT_LOG = "client/Logs/unity-project-files.log"  # where Unity says why the project files could not be regenerated
PROJECT_LOG_LINES = 20
FAILED_FIRST = " failed first"


@dataclass
class Round:
    """What a round has decided so far."""

    n: int  # the round's number in the run
    results: list[CheckResult] = field(default_factory=list)
    by_step: dict[int, CheckResult] = field(default_factory=dict)
    red: str = ""  # the group of the first red: later groups, and every expensive check, are skipped
    red_skipped: set[int] = field(default_factory=set)  # steps left out because of a red
    ran: dict[tuple[str, str], tuple[CheckResult, float]] = field(default_factory=dict)  # (command, directory) -> result, limit
    env: dict[str, str] = field(default_factory=dict)  # $TL_CHECK_LOG_/RC_<ID> of what ran, for the checks after it
    timings: list[tuple[str, float]] = field(default_factory=list)  # (command, secs) of what passed, for the duration history
    changed: list[str] | None = None


class CheckExecutor:
    def __init__(self, host: CheckHost, cache: CheckCache, keys: InputKeys, attempts: Attempts, checklog: CheckLog,
                 history: Durations) -> None:
        self.host, self.cache, self.keys, self.attempts, self.checklog, self.history = host, cache, keys, attempts, checklog, history
        self.logs = host.run_dir / "checks"

    def run_group(self, plan: CheckPlan, rnd: int) -> Round:
        """Run every step of the plan, in order, as one block (the cheap checks first, the Unity group last)."""
        st = Round(rnd, results=list(plan.skipped))
        self.logs.mkdir(exist_ok=True)
        for n, step in enumerate(plan.steps):
            res, cid = self._decide(step, n, st)
            st.results.append(res)
            st.by_step[n] = res
            self.checklog.close(step.check, res, cid, rnd)
        return st

    def _decide(self, step: Step, n: int, st: Round) -> tuple[CheckResult, str | None]:
        c = step.check
        skipped = self._skip(step, st)
        if skipped:
            if skipped.why.endswith(FAILED_FIRST):
                st.red_skipped.add(n)
            return skipped, None
        again = self._reused(c, st)
        if again:
            st.red = c.group if again.exit != 0 else st.red
            return again, None
        ikey, nocache = self._key(c)
        hit = self.cache.hit(c, ikey) if c.cache else None
        cid, name = None, self._log_name(n, c, st.n)
        if hit is not None:
            res, where = self.cache.cached(c, hit, ikey), hit.log_abs
            if res.note:
                self.host.log.note(f"cached: {c.id}, {res.note}")
        else:
            cid = self.checklog.start(c, st.n, "checks/" + name)
            res, where = self._launch(step, st, name, ikey, nocache), str(self.logs / name)
        st.ran[(norm(c.cmd), str(self.host.wt))] = (res, c.wall_min)
        self._publish(c, res, where, st)
        if res.exit != 0 and not res.base_red:
            st.red = c.group
        return res, cid

    @staticmethod
    def _log_name(n: int, c: Check, rnd: int) -> str:
        return f"{n:02d}-{safe_name(c.id)}.r{rnd}.log"

    def _skip(self, step: Step, st: Round) -> CheckResult | None:
        c = step.check
        gone = self._producer_gone(step, st)
        if gone:
            return CheckResult.skipped(c, f"producer {gone} did not run", producer=gone)
        if st.red and (c.group != st.red or expected_secs(c.cmd, self.history) >= CHEAP_S or step.unity
                       or any(d in st.red_skipped for d in step.after)):
            # a red group skips the groups after it, and any red skips every expensive check (the cheap ones of its own group run to
            # the end, so the writer sees all the cheap failures at once; the Unity group never runs after a red)
            return CheckResult.skipped(c, st.red + FAILED_FIRST)
        if c.when:
            st.changed = self.host.checkout.changed_paths() if st.changed is None else st.changed
            if not any(fnmatch.fnmatch(p, g) for p in st.changed for g in c.when):
                return CheckResult.skipped(c, "no change under {}".format(", ".join(c.when)))
        return None

    @staticmethod
    def _producer_gone(step: Step, st: Round) -> str:
        """The id of a check this one reads the log or exit code of that did not run, or ran red, or the repo does not have: it has
        nothing to read, and no write can change that. Such a check is skipped, never failed."""
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
        before = st.ran.get((norm(c.cmd), str(self.host.wt)))
        if before is None or (before[0].exit == 124 and before[1] < c.wall_min):
            return None
        self.host.log.note(f"`{c.cmd[:120]}` already ran in this block: its result is reused")
        return dataclasses.replace(before[0], id=c.id, cmd=c.cmd, group=c.group, cached=False, reused=True, log="")

    def _key(self, c: Check) -> tuple[str, bool]:
        """(the cache key of the check's inputs, whether this round may not cache it). A glob that selects nothing would cache a
        green over changed code."""
        if not (c.cache and c.inputs):
            return "", False
        dead = self.keys.dead(c)
        for g in dead:
            self.host.warn(f"inputs glob {g} matches no tracked file; not cached")
        return ("", True) if dead else (self.keys.key(c), False)

    def _publish(self, c: Check, res: CheckResult, log_abs: str, st: Round) -> None:
        """Later checks read this one's log and exit code: $TL_CHECK_LOG_<ID>, $TL_CHECK_RC_<ID>."""
        if c.group != "acceptance" and res.exit is not None and Path(log_abs).is_file():
            st.env[log_var(c.id)], st.env[rc_var(c.id)] = log_abs, str(res.exit)

    def _launch(self, step: Step, st: Round, name: str, ikey: str, nocache: bool) -> CheckResult:
        c = step.check
        t0 = time.time()
        out = self.attempts.run(c, self.logs / name, st.env)
        self._fault(c, out, st)
        res = self._result(c, out, name, round(time.time() - t0))
        if out.rc == 0:  # only a green run says what the check costs: a red one stops early
            st.timings.append((c.cmd, time.time() - t0))
            if c.cache and not nocache:
                self.cache.remember(c, res, st.n, str(self.logs / name), ikey)
        return res

    def _fault(self, c: Check, out: Outcome, st: Round) -> None:
        """Two reds that are not the code's: a tree older than the config it runs, and a check killed by a signal."""
        stale = stale_tree(out.seen or out.tail) if out.rc and c.repo else ""
        if stale:
            raise CheckFault(CheckFaultKind.STALE_BASE, f"failed: infrastructure: the configured check `{c.id}` needs something this tree "
                             f"lacks (\"{stale}\"): the tree is older than the base's .task-loop.json, which no writer can fix")
        if out.rc < 0 and not self.host.killed:
            raise CheckFault(CheckFaultKind.KILLED, f"failed: stopped: check `{c.id}` was killed by signal {-out.rc}; the bead goes "
                             "back to open and the next run runs it again (no fix round, no failure counted)")

    def _result(self, c: Check, out: Outcome, name: str, secs: int) -> CheckResult:
        tail = out.tail[-1500:]
        if out.rc and not out.base_red:
            tail += self._project_log(c, out.seen, self.logs / name)
        return CheckResult(id=c.id, cmd=c.cmd, group=c.group, exit=out.rc, status="passed" if out.rc == 0 else "failed", tries=out.tries,
                           tail=tail, secs=secs, log="checks/" + name, base_red=out.base_red, wall_hit=out.wall_hit, wall_min=c.wall_min,
                           sig=output_signature(out.seen) if out.rc else "")

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
