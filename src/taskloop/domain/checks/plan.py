"""CheckPlan: which checks a round runs, in which order, and what each one is launched as. Pure."""
from collections.abc import Sequence
from dataclasses import dataclass

from taskloop.contracts.checks import Check, CheckResult, Durations
from taskloop.contracts.ids import CheckId
from taskloop.domain.checks.order import CheckOrder


@dataclass(frozen=True)
class Step:
    """One check of the round. The numbers are positions in the plan."""

    check: Check
    env: tuple[int, ...]  # the checks whose $TL_CHECK_LOG_/RC_ it reads (Check.reads): the graph's edges into it
    absent: tuple[CheckId, ...]  # what it reads that is not in this round (a group left out, a conflict fix)
    unity: bool = False  # in the Unity group: after every cheaper check, skipped by any red


@dataclass(frozen=True)
class CheckPlan:
    steps: tuple[Step, ...]
    skipped: tuple[CheckResult, ...] = ()  # left out before the round began (a conflict fix)

    @classmethod
    def build(cls, items: Sequence[Check], history: Durations, groups: Sequence[str] | None = None,
              acceptance_first: bool = False, conflict_fix: Sequence[str] | None = None, markers: str = "") -> CheckPlan:
        """The round's steps from the repo's checks and the plan's. conflict_fix (the plan's check commands the fix skips, else
        None): a conflict fix runs the marker check and the repo's build checks only; the rest are recorded as skipped and the gate
        verifies the result. groups: only these groups (the cheap checks before a render)."""
        chosen: list[Check] = list(items)
        skipped: list[CheckResult] = []
        if conflict_fix is not None:
            chosen, skipped = _conflict_split(chosen, conflict_fix, markers)
        if groups:
            chosen = [c for c in chosen if c.group in groups]
        where = {c.id: i for i, c in enumerate(chosen)}
        env = {i: [where[r] for r in c.reads if r in where] for i, c in enumerate(chosen)}
        repo = [i for i, c in enumerate(chosen) if c.group != "acceptance"]
        unity = frozenset(i for i in repo if "unity" in chosen[i].tags)
        order = CheckOrder(history, acceptance_first).sort(chosen, env, unity)
        pos = {o: n for n, o in enumerate(order)}
        steps = tuple(Step(chosen[o], tuple(pos[e] for e in env[o]), tuple(r for r in chosen[o].reads if r not in where), o in unity)
                      for o in order)
        return cls(steps, tuple(skipped))


def _conflict_split(items: list[Check], fix: Sequence[str], markers: str) -> tuple[list[Check], list[CheckResult]]:
    keep = [c for c in items if c.cmd == markers or "diff" in c.tags or (c.repo and "build" in c.tags)]
    known = {c.cmd for c in items}
    skipped = [CheckResult.skipped(c, "conflict_fix") for c in items if c not in keep]
    skipped += [CheckResult.skipped(Check(id=CheckId(x), cmd=x, group="acceptance"), "conflict_fix")
                for x in dict.fromkeys(fix) if x != markers and x not in known]
    return keep, skipped
