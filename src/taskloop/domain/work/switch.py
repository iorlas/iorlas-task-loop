"""Review switches control intermediate stages. Every mode reviews the final stage against the bead's acceptance; plan case wording
and green checks cannot stand in for that review.

Used by: look, review, write, pipeline.
"""
from collections.abc import Collection
from typing import Final

OFF_LABEL: Final = "review-off"


def mode(configured: str, labels: Collection[str]) -> str:
    """The mode of one bead's run: the label skips intermediate reviews; otherwise the profile's."""
    return "off" if OFF_LABEL in labels else configured


def reviews(m: str, *, stage: int, last: bool, every: int) -> bool:
    """True when the stage (0-based) is reviewed under mode `m`; the final stage is mandatory."""
    if last:
        return True
    if m == "off":
        return False
    return m != "sampled" or (stage + 1) % max(1, every) == 0
