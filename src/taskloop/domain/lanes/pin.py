"""The writer family pin (engine.writer_family, label writer-family:<f>): which families delegate may pick for the write node.

Only the worker role is pinned; the planner and the reviewer (and the reflect call, a reviewer-role call) are never filtered. The
reviewer stays the other family through `--authored-by`, and delegate never answers with a family outside the pin: when none is ready it
stops (`only_family_unready`, or `no_lane`), and the engine says so in words instead of a generic failure."""

import hashlib
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Final

from tlkernel.delegate import REASON_ENGINE_ONLY_UNENFORCED, REASON_NO_LANE, REASON_ONLY_FAMILY

LABEL_PREFIX: Final = "writer-family:"
PINNED_ROLE: Final = "worker"
WARM_ONE_IN: Final = 10  # engine.second_writer_family: one light bead in this many is written by the second family
STOP_REASONS: Final = (REASON_ONLY_FAMILY, REASON_NO_LANE, REASON_ENGINE_ONLY_UNENFORCED)


@dataclass(frozen=True)
class Warm:
    """The second writer family of one bead: engine.second_writer_family, the bead's id, and whether its plan is light."""

    family: str
    bead: str
    light: bool


def is_light(stages: int, grant: bool) -> bool:
    """A light plan is one stage with no host execution grant; no plan yet (0 stages) is not known to be light."""
    return stages == 1 and not grant


def warm_second(bead: str, light: bool, second: str, labels: Collection[str], configured: Sequence[str]) -> list[str]:
    """[second] for the one light bead in ten that sha1(bead id) picks (the same bead, the same answer, on every run and machine), else [].
    Off when unset; never for a heavy plan, a bead that pins its own family, or when the profile already pins that family."""
    family = second.strip().lower()
    if not family or not light or any(s.startswith(LABEL_PREFIX) for s in labels) or [f.strip().lower() for f in configured] == [family]:
        return []
    return [family] if int(hashlib.sha1(bead.encode()).hexdigest(), 16) % WARM_ONE_IN == 0 else []


def families(configured: Sequence[str], labels: Collection[str], second: Warm | None = None) -> list[str]:
    """The pin of one bead: the families of its `writer-family:<f>` labels when it has any (they override the profile), else the second
    writer family when the bead is the chosen one in ten, else the profile's `engine.writer_family`. [] is no pin."""
    mine = sorted({s[len(LABEL_PREFIX):].strip().lower() for s in labels if s.startswith(LABEL_PREFIX)} - {""})
    if mine:
        return mine
    warm = warm_second(second.bead, second.light, second.family, labels, configured) if second else []
    return warm or [f.strip().lower() for f in configured if f.strip()]


def for_role(role: str, pinned: Sequence[str]) -> list[str]:
    """What `--only-family` carries on a call of `role`: the pin for the worker, nothing for any other role."""
    return list(pinned) if role == PINNED_ROLE else []


def describe(pinned: Sequence[str]) -> str:
    """The effective setting in a few words, for `tl doctor` and the run log."""
    if not pinned:
        return "writer_family: none (delegate picks the writer's family)"
    return (f"writer_family: {', '.join(pinned)} (every worker call carries --only-family; no other family writes; "
            "a bead label writer-family:<f> overrides)")


def describe_second(second: str) -> str:
    """engine.second_writer_family in a few words, for `tl doctor`."""
    family = second.strip().lower()
    if not family:
        return "second_writer_family: off"
    return f"second_writer_family: {family} (one light bead in {WARM_ONE_IN}, picked by bead id; that family alone, no fallback)"


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


def stop_why(node: str, pinned: Sequence[str], reason: str, said: str, fix: str = "", warm: str = "") -> str:
    """The `why` of a pinned write that delegate could not place: the pin and the reason in words."""
    if reason == REASON_ENGINE_ONLY_UNENFORCED:
        return unenforced_why(node, said, fix)
    fams = ", ".join(pinned)
    if warm:
        return (f"paused: this bead is the one in {WARM_ONE_IN} written by the second writer family ({warm}), and it has no ready lane for "
                f"{node} ({reason}): {said[:200]}; no other family is used. It runs when {warm} is ready, or unset "
                "engine.second_writer_family")
    return (f"paused: no ready lane of the pinned writer family ({fams}) for {node} ({reason}): {said[:200]}; "
            "no other family is used. It runs when that family is ready, or unpin it (engine.writer_family, label writer-family:<f>)")
