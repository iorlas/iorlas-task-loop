"""The plan as the run keeps it, and the plan as a worker is shown it. The planner's answer carries what only the engine's accept step
reads (is the stage risky, a question for the owner, its options, what was decided, what was left unresolved); once the plan is accepted
none of it is stored, published or sent to a worker."""
from collections.abc import Mapping
from typing import Any

PLAN_ONLY = ("question", "options", "decided", "unresolved")
STAGE_ONLY = ("hard",)
WORKER_SKIPS = ("risks", "cases", "leftovers", "stages")  # the assumptions, the summary and the rest stay


def stored(plan: dict[str, Any]) -> dict[str, Any]:
    """`plan` without the accept-step-only keys (in place; returns it)."""
    for k in PLAN_ONLY:
        plan.pop(k, None)
    for st in plan.get("stages") or []:
        for k in STAGE_ONLY:
            st.pop(k, None)
    return plan


def role_view(plan: Mapping[str, Any], n: int) -> dict[str, Any]:
    """What a writer or a reviewer of stage `n` (0-based) needs of the plan: the summary, its own stage whole, the other stages by goal
    and files. The risks, cases and leftovers reach it through its own prompt, not through the plan; the assumptions stay."""
    stages = [st if k == n else {"goal": st["goal"], "files": st["files"]} for k, st in enumerate(plan.get("stages") or [])]
    return {**{k: v for k, v in plan.items() if k not in WORKER_SKIPS}, "stages": stages}
