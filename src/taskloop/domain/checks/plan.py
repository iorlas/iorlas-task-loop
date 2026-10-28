"""CheckPlan: which checks a round runs, in which order, and what each one is launched as. Pure."""
from collections.abc import Sequence
from dataclasses import dataclass

from taskloop.contracts.checks import Check, CheckResult, Durations
from taskloop.domain.checks.matchers import env_refs, is_build, is_unity
from taskloop.domain.checks.names import mangle, norm
from taskloop.domain.checks.order import CheckOrder


@dataclass(frozen=True)
class Step:
    """One check of the round. The numbers are positions in the plan."""

    check: Check
    env: tuple[int, ...]  # repo checks whose $TL_CHECK_LOG_/RC_ it reads
    after: tuple[int, ...]  # everything it waits for: env and the repo check it copies
    absent: tuple[str, ...]  # $TL_CHECK_* names of checks the repo does not have
    unity: bool = False  # in the Unity group: after every cheaper check, skipped by any red


@dataclass(frozen=True)
class CheckPlan:
    steps: tuple[Step, ...]
    skipped: tuple[CheckResult, ...] = ()  # left out before the round began (a conflict fix)

    @classmethod
    def build(cls, items: Sequence[Check], history: Durations, groups: Sequence[str] | None = None,
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
        mine = {mangle(chosen[i].id): i for i in repo}
        env = {i: [mine[m] for m in env_refs(c.cmd) if m in mine] for i, c in enumerate(chosen)}
        after = {i: list(env[i]) for i in env}
        for w, c in enumerate(chosen):
            if c.group == "acceptance":
                after[w] += [r for r in repo if norm(chosen[r].cmd) == norm(c.cmd) and r not in after[w]]
        unity = frozenset(i for i in repo if is_unity(chosen[i].id + " " + chosen[i].cmd))
        order = CheckOrder(history, acceptance_first).sort(chosen, after, unity)
        pos = {o: n for n, o in enumerate(order)}
        steps = tuple(Step(chosen[o], tuple(pos[e] for e in env[o]), tuple(pos[a] for a in after[o]),
                           tuple(m for m in env_refs(chosen[o].cmd) if m not in mine), o in unity)
                      for o in order)
        return cls(steps, tuple(skipped))


def _conflict_split(items: list[Check], fix: Sequence[str], markers: str) -> tuple[list[Check], list[CheckResult]]:
    keep = [c for c in items if c.cmd == markers or (c.repo and is_build(c.id + " " + c.cmd))]
    known = {c.cmd for c in items}
    skipped = [CheckResult.skipped(c, "conflict_fix") for c in items if c not in keep]
    skipped += [CheckResult.skipped(Check(id=x, cmd=x, group="acceptance"), "conflict_fix")
                for x in dict.fromkeys(fix) if x != markers and x not in known]
    return keep, skipped
