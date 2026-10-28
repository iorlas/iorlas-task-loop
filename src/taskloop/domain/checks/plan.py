"""CheckPlan: which checks a round runs, in which order, and what each one is launched as. Pure."""
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from taskloop.contracts.checks import Check, CheckResult, Durations
from taskloop.domain.checks.matchers import canon, contains_cmd, env_refs, is_build, is_unity, reuse_log
from taskloop.domain.checks.names import log_var, mangle, rc_var
from taskloop.domain.checks.order import CheckOrder


@dataclass(frozen=True)
class Step:
    """One check of the round. The numbers are positions in the plan."""

    check: Check
    cmd: str  # what is launched: the check's command, or the same with a repo check's log read instead of run again
    reads: tuple[int, ...]  # repo checks whose log `cmd` reads
    env: tuple[int, ...]  # repo checks whose $TL_CHECK_LOG_/RC_ it reads
    after: tuple[int, ...]  # everything it waits for: env, reads and the repo check it copies
    absent: tuple[str, ...]  # $TL_CHECK_* names of checks the repo does not have
    unity: bool = False  # in the Unity group: after every cheaper check, skipped by any red


@dataclass(frozen=True)
class CheckPlan:
    steps: tuple[Step, ...]
    skipped: tuple[CheckResult, ...] = ()  # left out before the round began (a conflict fix)

    @classmethod
    def build(cls, items: Sequence[Check], history: Durations, exists: Callable[[str], bool], groups: Sequence[str] | None = None,
              acceptance_first: bool = False, conflict_fix: Sequence[str] | None = None, markers: str = "") -> "CheckPlan":
        """The round's steps from the repo's checks and the plan's. conflict_fix (the plan's check commands the fix skips, else
        None): a conflict fix runs the marker check and the repo's build checks only; the rest are recorded as skipped and the gate
        verifies the result. groups: only these groups (the cheap checks before a render)."""
        chosen: list[Check] = list(items)
        skipped: list[CheckResult] = []
        if conflict_fix is not None:
            chosen, skipped = _conflict_split(chosen, conflict_fix, markers)
        if groups:
            chosen = [c for c in chosen if c.group in groups]
        repo = [i for i, c in enumerate(chosen) if c.group != "acceptance"]
        run, reads = _reuse(chosen, repo, exists)
        mine = {mangle(chosen[i].id): i for i in repo}
        env = {i: [mine[m] for m in env_refs(c.cmd) if m in mine] for i, c in enumerate(chosen)}
        after = {i: env[i] + reads.get(i, []) for i in env}
        for w, c in enumerate(chosen):
            if c.group == "acceptance":
                after[w] += [r for r in repo if canon(chosen[r].cmd) == canon(c.cmd) and r not in after[w]]
        unity = frozenset(i for i in repo if is_unity(chosen[i].id + " " + chosen[i].cmd))
        order = CheckOrder(history, acceptance_first).sort(chosen, after, unity)
        pos = {o: n for n, o in enumerate(order)}
        steps = tuple(Step(chosen[o], run.get(o, chosen[o].cmd), tuple(pos[r] for r in reads.get(o, ())), tuple(pos[e] for e in env[o]),
                           tuple(pos[a] for a in after[o]), tuple(m for m in env_refs(chosen[o].cmd) if m not in mine), o in unity)
                      for o in order)
        return cls(steps, tuple(skipped))


def _conflict_split(items: list[Check], fix: Sequence[str], markers: str) -> tuple[list[Check], list[CheckResult]]:
    keep = [c for c in items if c.cmd == markers or (c.repo and is_build(c.id + " " + c.cmd))]
    known = {c.cmd for c in items}
    skipped = [CheckResult.skipped(c, "conflict_fix") for c in items if c not in keep]
    skipped += [CheckResult.skipped(Check(id=x, cmd=x, group="acceptance"), "conflict_fix")
                for x in dict.fromkeys(fix) if x != markers and x not in known]
    return keep, skipped


def _reuse(items: list[Check], repo: list[int], exists: Callable[[str], bool]) -> tuple[dict[int, str], dict[int, list[int]]]:
    """A plan check whose segment is exactly a repo check's command reads that check's log instead of running it again, when
    the repo check ran green in this round (reuse_log). Anything else (args, an env prefix, `||`, `!`, a subshell, a quoted
    mention) runs as written, and so does the repo check. -> ({index: command}, {index: [repo checks it reads]})."""
    run: dict[int, str] = {}
    reads: dict[int, list[int]] = {}
    for w, c in enumerate(items):
        if c.group != "acceptance":
            continue
        cmd = c.cmd
        for r in repo:
            rc, var = items[r], log_var(items[r].id)
            if not contains_cmd(cmd, rc.cmd, unquoted=True) or var in cmd or rc_var(rc.id) in cmd:
                continue
            new = reuse_log(cmd, rc.cmd, var, exists)
            if new:
                cmd = new
                reads.setdefault(w, []).append(r)
        run[w] = cmd
    return run, reads
