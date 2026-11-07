"""Policy over the bead's and the plan's prose: the only regexes of the plan feature, each a named matcher with a table test
(tests/plan/test_matchers.py)."""
import re
from typing import Final

from taskloop.domain.checks import lint
from tlkernel.bead import Bead
from tlkernel.config import EngineConfig
from tlkernel.paths import TASK_EXCLUDE
from tlkernel.plancheck import PlanData

_FILLER_TEXT: Final = (
    "the a an of and or is are be pass passes passed passing green succeed succeeds succeeded success "
    "clean ok okay exit exits exited code zero 0 run runs running ran must should shall without no error "
    "errors fail fails failure failures all full complete completes whole gate check checks done when it "
    "that on with"
)
GATE_FILLER: Final = frozenset(_FILLER_TEXT.split())
_GATE_PUNCT: Final = re.compile(r"[`'\"*_.,;:()\[\]]")
_HEADING: Final = re.compile(r"^#{1,6}\s*(?:Acceptance Criteria|Done when)\s*:?\s*$(.*?)(?=^#{1,6}\s|\Z)", re.M | re.S | re.I)
_DONE_LINE: Final = re.compile(r"^[ \t>*_#-]*Done when[ \t]*[:*_]+[ \t]*(?:[^\s:*_]|\n\s*[-*\d])", re.M | re.I)
_ACCEPT_START: Final = re.compile(r"^[ \t>*_#-]*(?:Acceptance Criteria|Done when)\b", re.M | re.I)


def evidence_files(bead: str, text: str) -> list[str]:
    """The evidence files (.task/<bead>/evidence/...) a check command names."""
    return re.findall(rf"{re.escape(TASK_EXCLUDE)}{re.escape(bead)}/evidence/[^\s\"'<>|;&)]+", text)


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


def gate_only_criteria(plan: PlanData, cfg: EngineConfig) -> list[str]:
    """The plan's cases (its acceptance) whose text is only a gate command, e.g. "`just check` passes". The engine runs the gate at
    land; a case for it proves nothing the land does not."""
    def clean(t: str) -> str:
        return " ".join(_GATE_PUNCT.sub(" ", t).lower().split())

    cmds = [clean(c) for c, _ in lint.gate_only(cfg)]
    out = []
    for x in plan.get("cases") or []:
        text = clean(x.get("criterion") or "")
        rest = text
        for c in sorted(cmds, key=len, reverse=True):
            rest = rest.replace(c, " ")
        if rest != text and not [w for w in rest.split() if w not in GATE_FILLER]:
            out.append(x.get("criterion", "").strip())
    return out
