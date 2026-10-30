"""A git call whose failure stops the run: git's error becomes the Blocked the engine raises, with git's words."""

from collections.abc import Callable
from typing import Protocol

from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError


class BlockedFor(Protocol):
    def blocked_for(self, why: str, kind: str) -> Exception: ...


def must[T](e: BlockedFor, what: str, call: Callable[[], T], kind: str = "FAULT_INFRA") -> T:
    """`call()`; a git failure raises `e.blocked_for("failed: `git <what>`: <git's words>")` (the run stops, the branch is kept)."""
    try:
        return call()
    except SlotGitError as err:
        raise e.blocked_for(f"failed: `git {what}`: {err}", kind) from err


def oneline(git: Git, d: str, include: list[str], exclude: list[str], limit: int) -> str:
    """The newest `limit` commits of `include` not on `exclude`, one `<short oid> <subject>` per line; empty when git cannot say."""
    try:
        return "\n".join(f"{r.oid[:7]} {r.subject}" for r in git.log(d, include, exclude, limit=limit))
    except SlotGitError:
        return ""
