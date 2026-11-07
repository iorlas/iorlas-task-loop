"""Where a bead states what done means in its acceptance field and description."""
import re
from typing import Final

from tlkernel.bead import Bead

_HEADING: Final = re.compile(r"^#{1,6}\s*(?:Acceptance Criteria|Done when)\s*:?\s*$(.*?)(?=^#{1,6}\s|\Z)", re.M | re.S | re.I)
_DONE_LINE: Final = re.compile(r"^[ \t>*_#-]*Done when[ \t]*[:*_]+[ \t]*(?:[^\s:*_]|\n\s*[-*\d])", re.M | re.I)
_ACCEPT_START: Final = re.compile(r"^[ \t>*_#-]*(?:Acceptance Criteria|Done when)\b", re.M | re.I)


class AcceptanceText:
    """Where a bead states what done means."""

    @staticmethod
    def present(bead: Bead) -> bool:
        """Criteria in the bead's field, or in a ## Acceptance Criteria or ## Done when section (or a "Done when:" line) of its
        description."""
        if bead.acceptance_criteria.strip():
            return True
        m = _HEADING.search(bead.description)
        if m and m.group(1).strip():
            return True
        return bool(_DONE_LINE.search(bead.description))

    @staticmethod
    def text(bead: Bead) -> str:
        """The criteria field, and the description from an Acceptance Criteria or Done when heading (or line) on."""
        desc = bead.description
        m = _ACCEPT_START.search(desc)
        return "\n".join(x for x in (bead.acceptance_criteria.strip(), desc[m.start():] if m else "") if x)
