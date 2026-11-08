"""The bead's opaque writer preference and its stop diagnostics."""
from collections.abc import Collection
from typing import Final

from tlkernel.delegate import REASON_ENGINE_ONLY_UNENFORCED, REASON_NO_ACCOUNT, REASON_ONLY_FAMILY

LABEL_PREFIX: Final = "writer-family:"
PINNED_ROLE: Final = "worker"
STOP_REASONS: Final = (REASON_ONLY_FAMILY, REASON_NO_ACCOUNT, REASON_ENGINE_ONLY_UNENFORCED)


def prefer_of(labels: Collection[str]) -> str:
    """The first sorted nonempty writer label, without interpreting its family token."""
    choices = sorted({label[len(LABEL_PREFIX):].strip() for label in labels if label.startswith(LABEL_PREFIX)} - {""})
    return choices[0] if choices else ""


def unenforced_why(node: str, said: str, fix: str = "") -> str:
    """An enforcement stop needs a harness or an explicit advisory call, not a wait for capacity."""
    return (f"paused: the writer's harness cannot deny the engine-only recipes: {said}"
            f"{(' [' + fix + ']') if fix else ''} ({REASON_ENGINE_ONLY_UNENFORCED}, {node}); "
            "use a harness that can deny them or enable --engine-only-advisory for the pinned writer")


def stop_why(node: str, prefer: str, reason: str, said: str, fix: str = "") -> str:
    """Explain a refused writer preference; delegate owns the routing policy."""
    if reason == REASON_ENGINE_ONLY_UNENFORCED:
        return unenforced_why(node, said, fix)
    return (f"paused: no ready account of the pinned writer family ({prefer}) for {node} ({reason}): {said[:200]}; "
            "no other family is used. It runs when that family is ready, or remove the label writer-family:<f>")
