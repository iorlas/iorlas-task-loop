"""The review switch (engine.review, label review-off): a pure rule for whether a stage gets a review at all. `off` never reviews;
`sampled` reviews every Nth stage (engine.review_every) and always the last. The last stage maps the bead's acceptance, which the
review would have done; with the review off a deterministic check stands in: every acceptance item must be named by a plan case (whose
check the engine ran), else that stage is reviewed after all."""
from collections.abc import Collection, Sequence
from typing import Final

from taskloop.domain.plan.matchers import word_set

OFF_LABEL: Final = "review-off"


def mode(configured: str, labels: Collection[str]) -> str:
    """The mode of one bead's run: the label turns the review off; otherwise the profile's."""
    return "off" if OFF_LABEL in labels else configured


def reviews(m: str, *, stage: int, last: bool, every: int) -> bool:
    """True when the stage (0-based) is reviewed under mode `m`."""
    if m == "off":
        return False
    return m != "sampled" or last or (stage + 1) % max(1, every) == 0


def covered(items: Sequence[tuple[str, str]], criteria: Sequence[str]) -> list[str]:
    """The ids of the acceptance items no case criterion names: at least two words, and half of the shorter side, are shared."""
    cases = [word_set(c) for c in criteria]
    out = []
    for key, text in items:
        mine = word_set(text)
        if not any(len(mine & c) >= max(2, min(len(mine), len(c)) // 2) for c in cases):
            out.append(key)
    return out
