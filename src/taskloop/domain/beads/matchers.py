"""Bead lint (tl-f52): a bead must be self-contained. Its text may not send the worker to material no worktree holds.

tl-7y6.6.15 stopped after 4 minutes because it cited sections of a study under ~/Documents/Drop. The detector is
conservative: it reports only references that cannot be read from a worktree, never a plain word like "study".
Escape for a false positive: the label `facts-inline`, or a line `facts-inline` (optionally `facts-inline: why`) in the text.
Pure functions.
"""

import re
from typing import Final

from taskloop.contracts.bead import Bead

ESCAPE_LABEL: Final = "facts-inline"
REASON: Final = "needs inlined facts"
FIELDS: Final = ("title", "description", "acceptance_criteria", "design", "notes")

_PATH: Final = r"""[^\s`'"<>)\]}]*"""
PATTERNS: Final = (
    ("a home path", re.compile(r"(?<![\w./-])~/" + _PATH.replace("*", "+", 1))),
    ("a home path", re.compile(r"(?<![\w.-])/(?:Users|home)/[\w.-]+/" + _PATH)),
    ("a Drop folder", re.compile(r"\bDocuments/Drop\b" + _PATH)),
    ("a study folder", re.compile(r"\barch-study[\w-]*" + _PATH, re.I)),
    ("a study reference", re.compile(r"\bstud(?:y|ies)\s+#?\d{1,3}\b", re.I)),
    ("a numbered study file", re.compile(r"(?<![\w/.-])\d{2,3}-[a-z][\w-]*\.md\b", re.I)),
)
ESCAPE_LINE: Final = re.compile(r"^\s*facts-inline\b", re.I | re.M)


def outside_root(path: str, root: str) -> bool:
    """True for an absolute path that is not under the repo root."""
    return bool(root) and path.startswith("/") and not (path == root or path.startswith(root.rstrip("/") + "/"))


def refs(bead: Bead, root: str = "") -> list[tuple[str, str]]:
    """[(kind, text)] this bead's text cites outside the repo; empty when the bead is self-contained or escaped."""
    if ESCAPE_LABEL in bead.labels:
        return []
    text = "\n".join(str(getattr(bead, f, "") or "") for f in FIELDS)
    if ESCAPE_LINE.search(text):
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            hit = m.group(0).rstrip(".,;:")
            if hit.startswith("/") and kind == "a home path" and root and not outside_root(hit, root):
                continue  # an absolute path under the repo root names a file the worktree has
            if not any(hit in x for x in seen):  # the Drop part of ~/Documents/Drop/x is the same reference
                seen.add(hit)
                out.append((kind, hit))
    return out


def why(bead: Bead, root: str = "") -> str:
    """The pick-step skip reason, or "" for a bead that is fine."""
    r = refs(bead, root)
    return f"{REASON} ({r[0][0]}: {r[0][1][:80]})" + (f" +{len(r) - 1} more" if len(r) > 1 else "") if r else ""


_TOUCHES: Final = re.compile(r"^\s*(?:[-*]\s*)?(?:#+\s*)?\**Touches\**\s*:?\**\s*(.*)$", re.I)
_BULLET: Final = re.compile(r"^\s*[-*]\s+(.*)$")
_WORDS: Final = re.compile(r"[\s,]+")
_OUTPUT: Final = re.compile(r"^\s*(?:[-*]\s*)?\**Output\**\s*:\**\s*(\S.*)$", re.I | re.M)
_AC_HEADING: Final = re.compile(r"^\s*#+\s*Acceptance Criteria\b", re.I | re.M)


def _paths(text: str) -> list[str]:
    return [w for x in _WORDS.split(text) if (w := x.strip("`'\",;"))]


def touches(text: str) -> list[str]:
    """The paths of the description's Touches field: the words after `Touches:` on its line, then the bullets right below it."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = _TOUCHES.match(ln)
        if not m:
            continue
        out = _paths(m.group(1))
        for nxt in lines[i + 1:]:
            b = _BULLET.match(nxt)
            if not b:
                break
            out += _paths(b.group(1))[:1]
        return out
    return []


def has_output(text: str) -> bool:
    return bool(_OUTPUT.search(text))


def has_ac_heading(text: str) -> bool:
    return bool(_AC_HEADING.search(text))
