"""The writer family pin (engine.writer_family, label writer-family:<f>): which families delegate may pick for the write node.

Only the worker role is pinned; the planner and the reviewer (and the reflect call, a reviewer-role call) are never filtered. The
reviewer stays the other family through `--authored-by`, and delegate never answers with a family outside the pin: when none is ready it
stops (`only_family_unready`, or `no_lane`), and the engine says so in words instead of a generic failure."""

from collections.abc import Collection, Sequence
from typing import Final

from taskloop.contracts.delegate import REASON_ENGINE_ONLY_UNENFORCED, REASON_NO_LANE, REASON_ONLY_FAMILY

LABEL_PREFIX: Final = "writer-family:"
PINNED_ROLE: Final = "worker"
STOP_REASONS: Final = (REASON_ONLY_FAMILY, REASON_NO_LANE, REASON_ENGINE_ONLY_UNENFORCED)


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


def exec_allow_problem(grant: Sequence[Sequence[str]], configured: Sequence[str], labels: Collection[str],
                       contract: int, capabilities: object) -> str:
    """A host execution grant requires an explicit Codex writer and delegate's advertised enforcement capability."""
    if not grant:
        return ""
    if list(configured) != ["openai"] or families(configured, labels) != ["openai"]:
        return 'engine.writer_exec_allow requires engine.writer_family exactly ["openai"] and an openai bead pin (Codex writer)'
    if contract != 4 or not isinstance(capabilities, list) or "writer_exec_allow" not in capabilities:
        return "delegate lacks the contract 4 writer_exec_allow capability required by engine.writer_exec_allow"
    return ""


def unenforced_why(node: str, said: str, fix: str = "") -> str:
    """An enforcement stop needs a harness or an explicit advisory call, not a wait for capacity."""
    return (f"paused: the writer's harness cannot deny the engine-only recipes: {said}"
            f"{(' [' + fix + ']') if fix else ''} ({REASON_ENGINE_ONLY_UNENFORCED}, {node}); "
            "use a harness that can deny them or enable --engine-only-advisory for the pinned writer")


def stop_why(node: str, pinned: Sequence[str], reason: str, said: str, fix: str = "") -> str:
    """The `why` of a pinned write that delegate could not place: the pin and the reason in words."""
    if reason == REASON_ENGINE_ONLY_UNENFORCED:
        return unenforced_why(node, said, fix)
    fams = ", ".join(pinned)
    return (f"paused: no ready lane of the pinned writer family ({fams}) for {node} ({reason}): {said[:200]}; "
            "no other family is used. It runs when that family is ready, or unpin it (engine.writer_family, label writer-family:<f>)")
