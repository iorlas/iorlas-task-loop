"""Read-only rows of `rounds.log` for a person (the dashboard): display only, never control state. A line that is not
the writer's grammar (`round_log.stamped`, `round_trail.Trail`, `rounds`) is skipped, never an error."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, get_args

from taskloop.evidence_files import EvidenceFiles
from taskloop.operations import Action
from taskloop.round_log import IDENT

ACTIONS: Final = frozenset(get_args(Action.__value__))
TASKLESS: Final = frozenset({"round", "rounds"})  # `round moves=N [stopped=X]` and `rounds started|wait|stopped ...`
ATTEMPT_LENGTH: Final = 32  # an attempt id is `uuid4().hex`
HEX: Final = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class LogRow:
    """One round-log line: `at` the UTC time as written; `move` an action word, `round`, `rounds` or a task-less first
    word (`no_free_slot`, `unusable:<slot>:<why>`); `step` and `attempt_id` only on a task's line that names them."""

    at: str
    backlog: str
    task: str | None
    step: str | None
    move: str
    words: tuple[str, ...]
    attempt_id: str | None


def timestamp(word: str) -> bool:
    try:
        datetime.strptime(word, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def parse_round_line(line: str) -> LogRow | None:
    """The row for one line, None when it does not start with a UTC time, a backlog and a word."""
    tokens = line.strip().split(" ")
    if len(tokens) < 3 or not timestamp(tokens[0]) or not IDENT.fullmatch(tokens[1]) or "" in tokens:
        return None
    at, backlog, rest = tokens[0], tokens[1], tokens[2:]
    if rest[0] in TASKLESS or not any(word in ACTIONS for word in rest[1:3]):
        return LogRow(at, backlog, None, None, rest[0], tuple(rest[1:]), None)
    step = None if rest[1] in ACTIONS else rest[1]
    words = rest[1 if step is None else 2 :]
    attempt = None
    if len(words) > 2 and len(words[-1]) == ATTEMPT_LENGTH and set(words[-1]) <= HEX:
        attempt = words.pop()
    return LogRow(at, backlog, rest[0], step, words[0], tuple(words[1:]), attempt)


def read_round_log(files: EvidenceFiles, limit: int = 200) -> tuple[LogRow, ...]:
    """The last `limit` lines that parse, oldest first."""
    return tuple(row for line in files.round_tail(limit) if (row := parse_round_line(line)) is not None)
