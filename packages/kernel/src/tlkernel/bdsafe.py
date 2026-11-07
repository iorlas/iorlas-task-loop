"""Shared bd calls whose refusal means absence or changes nothing."""
from collections.abc import Callable

from tlkernel.bead import Bead
from tlkernel.beadsport import BdFailure, Beads
from tlkernel.ids import BeadId


def peek(store: Beads, bead_id: BeadId) -> Bead | None:
    """The bead, None when it is not there or bd could not be asked."""
    try:
        return store.show(bead_id)
    except BdFailure:
        return None


def attempt[**P](call: Callable[P, object], *args: P.args, **kw: P.kwargs) -> bool:
    """A bd write whose refusal changes nothing: True when it worked."""
    try:
        call(*args, **kw)
        return True
    except BdFailure:
        return False


def listed[**P, T](call: Callable[P, list[T]], *args: P.args, **kw: P.kwargs) -> list[T]:
    """The beads a bd read lists, none when bd could not be asked."""
    try:
        return call(*args, **kw)
    except BdFailure:
        return []
