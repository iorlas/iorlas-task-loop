"""Policy over the bead's and the plan's prose: the only regexes of the plan feature, each a named matcher with a table test
(tests/plan/test_matchers.py)."""
import re

from taskloop.contracts.bead import Bead
from taskloop.contracts.config import EngineConfig
from taskloop.domain.checks import lint

STOP_WORDS = frozenset({"that", "this", "with", "from", "into", "have", "been", "were", "which", "their", "there", "than", "then", "when",
                        "what", "does", "should", "would", "could", "also", "only", "each", "every", "about", "after", "before", "bead",
                        "beads", "task", "work", "tests", "test", "file", "files", "code", "check", "checks"})
_FILLER_TEXT = (
    "the a an of and or is are be pass passes passed passing green succeed succeeds succeeded success "
    "clean ok okay exit exits exited code zero 0 run runs running ran must should shall without no error "
    "errors fail fails failure failures all full complete completes whole gate check checks done when it "
    "that on with"
)
GATE_FILLER = frozenset(_FILLER_TEXT.split())
GATE_RUNNER = re.compile(r"^(?:just|make|npm run|npm|yarn|pnpm run|pnpm|cargo|task|poe|tox|nox)\s+")
_WORD = re.compile(r"[^\W_]{3,}")
_GATE_PUNCT = re.compile(r"[`'\"*_.,;:()\[\]]")
_HEADING = re.compile(r"^#{1,6}\s*(?:Acceptance Criteria|Done when)\s*:?\s*$(.*?)(?=^#{1,6}\s|\Z)", re.M | re.S | re.I)
_DONE_LINE = re.compile(r"^[ \t>*_#-]*Done when[ \t]*[:*_]+[ \t]*(?:[^\s:*_]|\n\s*[-*\d])", re.M | re.I)
_ACCEPT_START = re.compile(r"^[ \t>*_#-]*(?:Acceptance Criteria|Done when)\b", re.M | re.I)


def word_set(text: object) -> set[str]:
    """The words of `text` worth comparing: lower case, 3+ letters or digits (any script), no filler."""
    return {w for w in _WORD.findall(str(text).lower()) if w not in STOP_WORDS}


def without_runner(cmd: str) -> str:
    """The command without its task runner (`just unity-tests` -> `unity-tests`)."""
    return GATE_RUNNER.sub("", cmd)


def bead_ids(prefix: str, text: str) -> list[str]:
    """The ids of beads with prefix `prefix` that `text` names, in order, once each."""
    found = re.findall(rf"(?<![\w.-])({re.escape(prefix)}-[A-Za-z0-9]+(?:\.[0-9]+)*)", text)
    return list(dict.fromkeys(found))


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


def gate_only_criteria(plan: dict, cfg: EngineConfig) -> list[str]:
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
