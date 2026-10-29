"""Fixer: the fix command of a check (a formatter) runs before the round, so the tree the checks see is already formatted."""
import fnmatch

from taskloop.app.checks.host import CheckHost
from taskloop.contracts.argv import argv_of
from taskloop.contracts.checks import Check, CheckResult
from taskloop.domain.checks.matchers import output_signature, safe_name
from taskloop.domain.checks.plan import CheckPlan


class Fixer:
    def __init__(self, host: CheckHost) -> None:
        self.host = host

    def run(self, plan: CheckPlan, rnd: int) -> dict[str, CheckResult]:
        """Run the fix of each repo check the round would run, once per distinct command, in the worktree. What it changed is staged
        like the stage's own changes and noted. -> {check id: its red result} for a fix that failed (that check is red and its own
        command does not run; the checks after it run as usual)."""
        host = self.host
        todo = [s.check for s in plan.steps if s.check.fix and self._due(s.check)]
        if not todo:
            return {}
        (host.run_dir / "checks").mkdir(exist_ok=True)
        before = host.checkout.tree_hash()
        done: dict[str, tuple[int, str]] = {}
        red: dict[str, CheckResult] = {}
        for n, c in enumerate(todo):
            if c.fix not in done:
                done[c.fix] = self._once(c, f"{n:02d}-{safe_name(c.id)}.fix.r{rnd}.log")
            rc, tail = done[c.fix]
            if rc:
                red[c.id] = self._red(c, rc, tail, f"checks/{n:02d}-{safe_name(c.id)}.fix.r{rnd}.log")
        after = host.checkout.tree_hash()
        if after != before:
            files = [p for p in host.git("diff", "--name-only", before, after).splitlines() if p]
            host.checkout.stage_all(check=True)
            host.log.note(f"fmt: fixed {len(files)} files ({', '.join(c.id for c in todo)})")
        return red

    def _due(self, c: Check) -> bool:
        """A check the round skips for its `when` does not fix either."""
        if not c.when:
            return True
        return any(fnmatch.fnmatch(p, g) for p in self.host.checkout.changed_paths() for g in c.when)

    def _once(self, c: Check, name: str) -> tuple[int, str]:
        return self.host.sh(argv_of(c.fix), timeout=c.wall_min * 60, save=self.host.run_dir / "checks" / name, what="check fix")

    @staticmethod
    def _red(c: Check, rc: int, tail: str, log: str) -> CheckResult:
        tail = f"the fix command `{c.fix}` failed (exit {rc})\n{tail[-1500:]}"
        return CheckResult(id=c.id, cmd=c.cmd, group=c.group, exit=rc, status="failed", tail=tail, log=log, wall_min=c.wall_min,
                           sig=output_signature(tail))
