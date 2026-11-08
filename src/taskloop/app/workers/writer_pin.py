"""Only the worker forwards a bead's writer preference."""
from collections.abc import Collection

from taskloop.domain.accounts import pin


def prefer(bead_labels: Collection[str], role: str) -> str:
    return pin.prefer_of(bead_labels) if role == pin.PINNED_ROLE else ""
