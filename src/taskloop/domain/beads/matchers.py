"""Bead lint (tl-f52): a bead must be self-contained. Its text may not send the worker to material no worktree holds.

tl-7y6.6.15 stopped after 4 minutes because it cited sections of a study under ~/Documents/Drop. The detector is
conservative: it reports only references that cannot be read from a worktree, never a plain word like "study".
Escape for a false positive: the label `facts-inline`, or a line `facts-inline` (optionally `facts-inline: why`) in the text.
Pure functions.
"""

import re

from taskloop.contracts.bead import Bead

ESCAPE_LABEL = "facts-inline"
REASON = "needs inlined facts"
FIELDS = ("title", "description", "acceptance_criteria", "design", "notes")

_PATH = r"""[^\s`'"<>)\]}]*"""
PATTERNS = (
    ("a home path", re.compile(r"(?<![\w./-])~/" + _PATH.replace("*", "+", 1))),
    ("a home path", re.compile(r"(?<![\w.-])/(?:Users|home)/[\w.-]+/" + _PATH)),
    ("a Drop folder", re.compile(r"\bDocuments/Drop\b" + _PATH)),
    ("a study folder", re.compile(r"\barch-study[\w-]*" + _PATH, re.I)),
    ("a study reference", re.compile(r"\bstud(?:y|ies)\s+#?\d{1,3}\b", re.I)),
    ("a numbered study file", re.compile(r"(?<![\w/.-])\d{2,3}-[a-z][\w-]*\.md\b", re.I)),
)
ESCAPE_LINE = re.compile(r"^\s*facts-inline\b", re.I | re.M)


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
