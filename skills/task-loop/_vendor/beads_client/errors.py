"""One typed failure for every way a bd call can go wrong."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ErrorKind = Literal[
    "not_found",
    "not_claimable",
    "precondition",
    "lint",
    "malformed",
    "missing_binary",
    "timeout",
    "version",
    "other",
]


@dataclass(frozen=True)
class BdErrorInfo:
    kind: ErrorKind
    text: str = ""
    missing_sections: tuple[str, ...] = field(default_factory=tuple)


class BdError(Exception):
    """bd refused or could not be asked. ``kind`` says which; ``precondition`` means an --if-assignee/--if-status fence
    no longer held (bd exit 13): nothing was written and retrying the same fence is pointless."""

    def __init__(self, kind: ErrorKind, text: str = "", missing_sections: tuple[str, ...] = ()) -> None:
        super().__init__(f"{kind}: {text}")
        self.kind: ErrorKind = kind
        self.text = text
        self.missing_sections = missing_sections


def malformed(text: str) -> BdError:
    return BdError("malformed", text)


def version_mismatch(text: str) -> BdError:
    return BdError("version", text)
