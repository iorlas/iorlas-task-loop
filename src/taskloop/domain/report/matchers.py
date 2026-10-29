"""Stable run fingerprints and the start reasons of a run.

A fingerprint is what groups failures (the storm detector, the retry escalation, the close comment): the same cause
with different bead ids, session refs, paths, commit shas, durations or quoted payloads must produce the same string,
while two different causes must not. It is derived from the run's `why` only, never from the run name or the clock, so it can be recomputed
from a trace row years later.

Pure; the regexes live here because nothing else in domain may import `re`.
"""

import hashlib
import os
import re
import time
from datetime import datetime, timedelta

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


HASH_TAIL = re.compile(r"#[0-9a-f]{8}$")


def fingerprint_head(why: object) -> str:
    """`fingerprint` without the hash of a long tail: a storm is the same head."""
    return HASH_TAIL.sub("", fingerprint(why))


def run_fingerprint(outcome: object, why: object) -> str:
    """A trace row's fingerprint: "" for a landed/done run, else the normalised cause (never empty)."""
    if str(outcome or "") in ("landed", "done"):
        return ""
    return fingerprint(why) or "unknown"


# ---- what `tl report` and the reflect digest read out of text ------------------------------------------------------------------------

# how the supervising session marks its own answers ("relayed by Claude" carries the owner's words: the owner's)
SUPERVISOR = re.compile(r"\(Claude, supervising|checked by Claude|delegated the call to Claude")
ANSWERED = re.compile(r"\bask (\S+) \(\w+\) is answered|\banswered verify ask (\S+)")
STEM = re.compile(r"^(.+)-(\d{8}-\d{6})$")
LAND_TAIL = re.compile(r"\(([^()\s]+)\)\s*$")
BACK = re.compile(r"^(\d+(?:\.\d+)?)\s*([mhd])$")
CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
HOURS = re.compile(r"(\d+)h")
EPOCH = re.compile(r"^\d{9,}(\.\d+)?$")
WORD = re.compile(r"[^\W\d_]{4,}")
FILE = re.compile(r"[\w./-]+\.(?:py|md|cs|json|ya?ml|toml|html|js|ts|sh|cfg|txt)\b")
GIT_SUFFIX = re.compile(r"\.git$")


def parse_time(text: str | None, now: float, forward: bool = False) -> float:
    """Epoch seconds for T: a duration back from now (90m, 12h, 2d), ISO (naive = local time), or HH:MM: its last
    past occurrence (a morning --since 22:00 is last night), with forward its next one (--until)."""
    s = (text or "").strip()
    m = BACK.match(s)
    if m:
        return now - float(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
    m = CLOCK.match(s)
    if m:
        t = datetime.fromtimestamp(now).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if forward and t.timestamp() < now:
            t += timedelta(days=1)
        elif not forward and t.timestamp() > now:
            t -= timedelta(days=1)
        return t.timestamp()
    try:
        d = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        raise ValueError(f"not a time: {text!r} (use ISO, HH:MM or a duration like 12h)") from None
    return d.timestamp()


def window_time(text: str, now: float) -> float:
    """`tl reflect digest --since/--until`: Nh back, epoch seconds, or anything parse_time takes."""
    s = text.strip()
    m = HOURS.fullmatch(s)
    if m:
        return now - int(m.group(1)) * 3600
    return float(s) if EPOCH.match(s) else parse_time(text, now)


def stem_time(stamp: str) -> float:
    """Epoch seconds of the YYYYMMDD-HHMMSS tail of an engine log's name (local time)."""
    return time.mktime(time.strptime(stamp, "%Y%m%d-%H%M%S"))


def supervised(text: str) -> bool:
    return bool(SUPERVISOR.search(text))


def answered_ask(text: str) -> str:
    """The ask id a log note says is answered, else ''."""
    m = ANSWERED.search(text)
    return (m.group(1) or m.group(2)) if m else ""


def split_stem(stem: str) -> tuple[str, str] | None:
    """(bead, YYYYMMDD-HHMMSS) of an engine log's stem, None when it is not one."""
    m = STEM.match(stem)
    return (m.group(1), m.group(2)) if m else None


STALE_TAIL = re.compile(r"-stale-\d{8}-\d{6}$")


def unstale(name: str) -> tuple[str, bool]:
    """A task branch name without the `-stale-<YYYYmmdd-HHMMSS>` tail --fresh gives the branch it sets aside: (the bead, set aside)."""
    bare = STALE_TAIL.sub("", name)
    return bare, bare != name


def land_bead(subject: str) -> str:
    """The bead a land commit's subject names: '... (<bead>)', else ''."""
    m = LAND_TAIL.search(subject)
    return m.group(1) if m else ""


def words(text: object) -> set[str]:
    """The lower-case words of 4 letters or more."""
    return set(WORD.findall(str(text).lower()))


def files_named(text: str) -> set[str]:
    """The base names of the files a text names."""
    return {os.path.basename(f) for f in FILE.findall(text)}


def repo_name(value: str) -> str:
    """The folder name a repo URL or path ends in."""
    return GIT_SUFFIX.sub("", value.rstrip("/").replace(":", "/").split("/")[-1])
