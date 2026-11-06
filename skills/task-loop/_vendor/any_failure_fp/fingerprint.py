"""A stable, readable slug for a failure reason: the same cause with different ids, paths or numbers collides."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

ANSI: Final = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
URL: Final = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
UUID: Final = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
SHA: Final = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
SESSION: Final = re.compile(r"\b(?:ref|ses|session|run|thread)[-_][A-Za-z0-9._-]+\b", re.IGNORECASE)
# Absolute POSIX/Windows paths, and relative paths with a separator and a file extension; a bare and/or is no path.
PATH: Final = re.compile(
    r"(?:[A-Za-z]:)?(?:[\\/][\w.@%+~-]+){2,}"
    r"|(?:[\w.@%+~-]+[\\/])+[\w.@%+~-]*\.[A-Za-z0-9]{1,8}\b"
)
QUOTED: Final = re.compile(r"`[^`]*`|\"[^\"]*\"|'[^']*'")
BRACES: Final = re.compile(r"\{[^{}]*\}")
NUMBER: Final = re.compile(r"\b\d+(?:\.\d+)?\b")
SPACE: Final = re.compile(r"\s+")
EDGE: Final = " :;,.-|/"
HASH_TAIL: Final = re.compile(r"#[0-9a-f]{8}$")
_CUT: Final = 8  # the room the "#" + 8 hex digits take


def fingerprint(text: object, *, ids: Mapping[str, re.Pattern[str]] | None = None, tail: int = 120) -> str:
    """The slug of `text` ("" when it says nothing).

    `ids` maps a label to a host-specific id pattern (a ticket key, a bead id); each match becomes `<label>`.
    Text longer than `tail` is cut to `tail - 8` characters plus `#` and 8 hex digits of its sha1, so two long
    reasons that differ only in the tail stay apart; `head` drops that suffix.
    """
    raw = "" if text is None else str(text)
    if not raw.strip():
        return ""
    s = ANSI.sub("", raw).lower()
    s = URL.sub(" <url> ", s)
    # Whole paths before sessions and embedded SHAs/UUIDs: Assets/Player2.cs is a path, and
    # /repo/thread-1234abc/Player.cs is one path, not a session plus a sha.
    s = PATH.sub(" <path> ", s)
    s = SESSION.sub(" <session> ", s)
    s = UUID.sub(" <id> ", s)
    s = SHA.sub(" <sha> ", s)
    for label, pattern in (ids or {}).items():
        s = pattern.sub(f" <{label}> ", s)
    s = QUOTED.sub(" <quoted> ", s)
    s = BRACES.sub(" <json> ", s)
    s = NUMBER.sub(" <n> ", s)
    s = SPACE.sub(" ", s).strip(EDGE)
    if len(s) > tail:
        s = s[: tail - _CUT].rstrip(EDGE) + "#" + hashlib.sha1(s.encode("utf-8"), usedforsecurity=False).hexdigest()[:_CUT]
    return s


def head(fp: str) -> str:
    """`fp` without the hash of a long tail: a storm is the same head."""
    return HASH_TAIL.sub("", fp)
