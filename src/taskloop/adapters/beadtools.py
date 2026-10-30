"""The bd of this session and the three ways a caller treats a refusal (end the command, an empty answer, carry on)."""
import shutil
import sys
from collections.abc import Callable
from typing import Any, TypeVar

from taskloop.adapters.bd import BdStore
from taskloop.adapters.ident import actor
from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, Beads

T = TypeVar("T")


def bd_store(cwd: object = None) -> BdStore:
    """The bd of this session (adapters/bd.py, the one place that starts `bd`), asking the tracker of `cwd` (default: here)."""
    if not shutil.which("bd"):
        sys.exit("tl: bd is not on PATH")
    return BdStore(actor(), str(cwd) if cwd else None)


def peek(store: Beads, bead_id: BeadId) -> Bead | None:
    """The bead, None when it is not there or bd could not be asked (a caller that must tell the two apart calls store.show)."""
    try:
        return store.show(bead_id)
    except BdFailure:
        return None


def must[T](call: Callable[..., T], *args: Any) -> T:
    """A bd write that ends the command when bd refuses."""
    try:
        return call(*args)
    except BdFailure as e:
        sys.exit("tl: " + e.error.text)


def listed[T](call: Callable[..., list[T]], *args: Any) -> list[T]:
    """The beads a bd read lists, none when bd could not be asked."""
    try:
        return call(*args)
    except BdFailure:
        return []


def attempt(call: Callable[..., object], *args: Any, **kw: Any) -> bool:
    """A bd write whose refusal changes nothing: True when it worked."""
    try:
        call(*args, **kw)
        return True
    except BdFailure:
        return False
