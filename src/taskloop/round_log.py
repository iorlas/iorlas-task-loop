"""The grammar of `rounds.log`: one line is the UTC time, a backlog and fixed words. The words are validated here so that
an arbitrary string is never written; the entry log reader's word shape (`WORD`) is the same."""

import re
from datetime import UTC, datetime
from typing import Final

WORD: Final = re.compile(r"(?:[a-z]+=)?[A-Za-z0-9_]{1,60}(?::[A-Za-z0-9_]{1,60}){0,2}")
IDENT: Final = re.compile(r"[A-Za-z0-9._:@+/-]{1,128}")  # a backlog, task or attempt id as a log word
INTERRUPTED: Final = "interrupted"  # the round's stopped word after a graceful stop; replaces any admission word


def stamped(now: float, backlog: str, *words: str) -> str:
    """One round-log line (`rounds.log`): the UTC time, the backlog and fixed words; `rounds` writes the same."""
    return " ".join([datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), ident(backlog), *words])


def fixed(word: str) -> str:
    return word if WORD.fullmatch(word) else "invalid"


def ident(value: str) -> str:
    return value if IDENT.fullmatch(value) else "invalid"
