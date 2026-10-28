"""Stable run fingerprints and the start reasons of a run.

A fingerprint is what groups failures (the storm detector, the retry escalation, the close comment): the same cause
with different bead ids, session refs, paths, commit shas, durations or quoted payloads must produce the same string,
while two different causes must not. It is derived from the run's `why` only, never from the run name or the clock, so it can be recomputed
from a trace row years later.

Pure; the regexes live here because nothing else in domain may import `re`.
"""

import hashlib
import re

# origin() writes one of these; an older row may have none at all.
STARTED_BECAUSE = ("first", "answer", "resume", "retry", "fresh")

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
URL = re.compile(r"\bhttps?://\S+", re.I)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
SHA = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)
# A token that may be a bead id: tl-19i, lifesim-d5f.46, tl-fsj, t-1-1. _bead_token decides.
CANDIDATE = re.compile(r"\b[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+\b", re.I)
BEAD_PREFIXES = ("tl", "lifesim", "task", "bead", "fld")
SESSION = re.compile(r"\b(?:ref|ses|session|run|thread)[-_][A-Za-z0-9._-]+\b", re.I)
# Absolute POSIX/Windows paths, and relative paths with a separator and a file extension (Assets/Player.cs,
# Assets\Player.cs). A bare word pair such as and/or is not a path.
PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.@%+~-]+){2,}"
                  r"|(?:[\w.@%+~-]+[\\/])+[\w.@%+~-]*\.[A-Za-z0-9]{1,8}\b")
QUOTED = re.compile(r"`[^`]*`|\"[^\"]*\"|'[^']*'")
BRACES = re.compile(r"\{[^{}]*\}")
NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
SPACE = re.compile(r"\s+")
EDGE = " :;,.-|/"


RUN_STAMP = re.compile(r"^\d{8}-\d{6}$")


def is_run_stamp(text: str) -> bool:
    """<YYYYMMDD-HHMMSS>: the tail of an engine log of a bead, not of a child bead."""
    return bool(RUN_STAMP.match(text))


def normalize_started_because(value: object, prev_run: object = "") -> str:
    """One of STARTED_BECAUSE: an older or damaged value becomes retry (a run came before) or first."""
    v = str(value or "").strip().lower()
    if v in STARTED_BECAUSE:
        return v
    return "retry" if str(prev_run or "").strip() else "first"


def _bead_token(token: str) -> bool:
    """True when token is an id, not a descriptive hyphenated word."""
    if any(ch.isdigit() for ch in token):
        return True
    return re.split(r"[.-]", token)[0].lower() in BEAD_PREFIXES


def fingerprint(why: object) -> str:
    """A stable, readable slug for a failure reason ("" when there is no text)."""
    text = str(why or "")
    if not text.strip():
        return ""
    text = ANSI.sub("", text).lower()
    text = URL.sub(" <url> ", text)
    # Whole paths before sessions and before embedded SHAs/UUIDs: Assets/Player2.cs is a path, not a bead, and
    # /repo/thread-1234abc/Player.cs is one path, not a session plus a sha. Paths first also keeps a session-like
    # segment inside a Windows or POSIX path from being split off.
    text = PATH.sub(" <path> ", text)
    text = SESSION.sub(" <session> ", text)
    text = UUID.sub(" <id> ", text)
    text = SHA.sub(" <sha> ", text)
    text = CANDIDATE.sub(lambda m: " <bead> " if _bead_token(m.group(0)) else m.group(0), text)
    text = QUOTED.sub(" <quoted> ", text)
    text = BRACES.sub(" <json> ", text)
    text = NUMBER.sub(" <n> ", text)
    text = SPACE.sub(" ", text).strip(EDGE)
    if not text:
        return ""
    if len(text) > 120:
        text = text[:112].rstrip(EDGE) + "#" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return text


def run_fingerprint(outcome: object, why: object) -> str:
    """A trace row's fingerprint: "" for a landed/done run, else the normalised cause (never empty)."""
    if str(outcome or "") in ("landed", "done"):
        return ""
    return fingerprint(why) or "unknown"

