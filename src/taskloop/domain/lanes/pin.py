"""The writer family pin (engine.writer_family, label writer-family:<f>): which families delegate may pick for the write node.

Only the worker role is pinned; the planner and the reviewer (and the reflect call, a reviewer-role call) are never filtered. The
reviewer stays the other family through `--authored-by`, and delegate never answers with a family outside the pin: when none is ready it
stops (`only_family_unready`, or `no_lane`), and the engine says so in words instead of a generic failure."""

from collections.abc import Collection, Sequence
from typing import Final

from taskloop.contracts.delegate import REASON_NO_LANE, REASON_ONLY_FAMILY

LABEL_PREFIX: Final = "writer-family:"
PINNED_ROLE: Final = "worker"
STOP_REASONS: Final = (REASON_ONLY_FAMILY, REASON_NO_LANE)


def families(configured: Sequence[str], labels: Collection[str]) -> list[str]:
    """The pin of one bead: the families of its `writer-family:<f>` labels when it has any (they override the profile), else the
    profile's `engine.writer_family`. [] is no pin."""
    mine = sorted({s[len(LABEL_PREFIX):].strip().lower() for s in labels if s.startswith(LABEL_PREFIX)} - {""})
    return mine or [f.strip().lower() for f in configured if f.strip()]


def for_role(role: str, pinned: Sequence[str]) -> list[str]:
    """What `--only-family` carries on a call of `role`: the pin for the worker, nothing for any other role."""
    return list(pinned) if role == PINNED_ROLE else []


def describe(pinned: Sequence[str]) -> str:
    """The effective setting in a few words, for `tl doctor` and the run log."""
    if not pinned:
        return "writer_family: none (delegate picks the writer's family)"
    return (f"writer_family: {', '.join(pinned)} (every worker call carries --only-family; no other family writes; "
            "a bead label writer-family:<f> overrides)")


def stop_why(node: str, pinned: Sequence[str], reason: str, said: str) -> str:
    """The `why` of a pinned write that delegate could not place: the pin and the reason in words."""
    fams = ", ".join(pinned)
    return (f"paused: no ready lane of the pinned writer family ({fams}) for {node} ({reason}): {said[:200]}; "
            "no other family is used. It runs when that family is ready, or unpin it (engine.writer_family, label writer-family:<f>)")
