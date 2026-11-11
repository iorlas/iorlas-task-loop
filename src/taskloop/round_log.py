"""The grammar of `rounds.log`: one line is the UTC time, a backlog and fixed words. The words are validated here so that
an arbitrary string is never written; the entry log reader's word shape (`WORD`) is the same. A word part takes the
profile's check-name alphabet and length (`[A-Za-z0-9._-]`, at most 64, not starting with `.` or `-`), so a checks
attempt's `failed:<check>:<conclusion>` stays one valid word."""

import re
from datetime import UTC, datetime
from typing import Final

PART: Final = r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}"
WORD: Final = re.compile(rf"(?:[a-z]+=)?{PART}(?::{PART}){{0,2}}")
IDENT: Final = re.compile(r"[A-Za-z0-9._:@+/-]{1,128}")  # a backlog, task or attempt id as a log word
INTERRUPTED: Final = "interrupted"  # the round's stopped word after a graceful stop; replaces any admission word


def stamped(now: float, backlog: str, *words: str) -> str:
    """One round-log line (`rounds.log`): the UTC time, the backlog and fixed words; `rounds` writes the same."""
    return " ".join([datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), ident(backlog), *words])


def fixed(word: str) -> str:
    return word if WORD.fullmatch(word) else "invalid"


def ident(value: str) -> str:
    return value if IDENT.fullmatch(value) else "invalid"
