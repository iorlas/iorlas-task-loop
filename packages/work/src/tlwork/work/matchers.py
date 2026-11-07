"""Policy over the bead's and the plan's prose: the only regexes of the plan feature, each a named matcher with a table test
(tests/plan/test_matchers.py).

Used by: plan, review, look, run.
"""
import re
from typing import Final

STOP_WORDS = frozenset({"that", "this", "with", "from", "into", "have", "been", "were", "which", "their", "there", "than", "then", "when",
                        "what", "does", "should", "would", "could", "also", "only", "each", "every", "about", "after", "before", "bead",
                        "beads", "task", "work", "tests", "test", "file", "files", "code", "check", "checks"})

GATE_RUNNER: Final = re.compile(r"^(?:just|make|npm run|npm|yarn|pnpm run|pnpm|cargo|task|poe|tox|nox)\s+")

_WORD: Final = re.compile(r"[^\W_]{3,}")


def word_set(text: object) -> set[str]:
    """The words of `text` worth comparing: lower case, 3+ letters or digits (any script), no filler."""
    return {w for w in _WORD.findall(str(text).lower()) if w not in STOP_WORDS}


def without_runner(cmd: str) -> str:
    """The command without its task runner (`just unity-tests` -> `unity-tests`)."""
    return GATE_RUNNER.sub("", cmd)


class Wording:
    """Words that say what an item is about: filing and recording (the ledger's own subject), the owner's call, a look."""

    FILING = re.compile(r"\b(?:beads?|follow-?ups?|filed?|filing|issues?|tickets?|records?|recorded|leftovers?|deferred?)\b", re.I)
    OWNERISH = re.compile(r"\b(?:owner|sign-?off|approv\w*|review|confirm\w*|decid\w*|decision)\b", re.I)
    LOOK = re.compile(r"owner\b[^.]{0,40}\b(?:judge|check|decide|assess|review|verify)\b[^.]*\b"
                      r"(?:looks?|visual\w*|appearance|screenshots?)\b", re.I)  # 'Only the owner can judge the look.'
    UNVERIFIED = re.compile(r"\bunverified\b", re.I)

    @classmethod
    def about_filing(cls, what: str) -> bool:
        return cls.FILING.search(what) is not None

    @classmethod
    def ownerish(cls, text: str) -> bool:
        return cls.OWNERISH.search(text) is not None

    @classmethod
    def is_look(cls, what: str) -> bool:
        return cls.LOOK.search(what) is not None

    @classmethod
    def marked_unverified(cls, line: str) -> bool:
        return cls.UNVERIFIED.search(line) is not None
