"""The outcome of one git child process, and the infrastructure error a failed one becomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from git_porcelain.errors import GitUnavailable

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["Done", "unavailable"]

_TAIL: Final = 600
_LOCKED: Final = ("index.lock", "cannot lock ref", "unable to create '", ".lock'")


@dataclass(frozen=True)
class Done:
    """A finished git child. Text is decoded with ``surrogateescape``, so ``raw`` round-trips any bytes."""

    rc: int
    raw: bytes
    err: str

    @property
    def out(self) -> str:
        return self.raw.decode("utf-8", "surrogateescape")

    @property
    def tail(self) -> str:
        return (self.err.strip() or self.out.strip())[-_TAIL:]


def unavailable(args: Sequence[str], done: Done) -> GitUnavailable:
    """The infrastructure failure of a git child that exited non-zero."""
    low = done.tail.lower()
    hint = "set user.name and user.email" if "tell me who you are" in low or "empty ident" in low else None
    return GitUnavailable(
        f"git {args[0] if args else ''} exited {done.rc}: {done.tail}",
        retryable=any(mark in low for mark in _LOCKED),
        hint=hint,
    )
