"""The outcome of one git child process, and the infrastructure error a failed one becomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from git_porcelain.diagnostic_output import redact_output
from git_porcelain.errors import GitUnavailable, failure

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["Done", "unavailable"]

_TAIL: Final = 600
_LOCKED: Final = ("index.lock", "cannot lock ref", "unable to create '", ".lock'")


@dataclass(frozen=True)
class Done:
    """A finished git child. Raw bytes are intact; diagnostic text replaces invalid UTF-8."""

    rc: int
    raw: bytes
    err: str
    hooks: tuple[str, ...] = ()
    hook_exits: tuple[tuple[str, int], ...] = ()

    @property
    def out(self) -> str:
        return self.raw.decode("utf-8", "replace")

    @property
    def tail(self) -> str:
        return redact_output(self.err.strip() or self.out.strip())[-_TAIL:]

    @property
    def output(self) -> str:
        return redact_output((self.out + self.err).strip())


def unavailable(args: Sequence[str], done: Done, *, full_output: bool = False) -> GitUnavailable:
    """The infrastructure failure of a git child that exited non-zero."""
    low = done.output.lower()
    hint = "set user.name and user.email" if "tell me who you are" in low or "empty ident" in low else None
    output = done.output
    return failure(
        f"git {args[0] if args else ''} exited {done.rc}: {output if full_output else done.tail}",
        done.err or done.out,
        done.rc,
        retryable=any(mark in low for mark in _LOCKED),
        hint=hint,
        output=output,
    )
