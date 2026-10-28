"""Two bd calls whose refusal changes nothing."""
from typing import Any

from taskloop.contracts.bead import Bead
from taskloop.contracts.ports import BdFailure


def peek(store: Any, bead_id: str) -> Bead | None:
    """The bead, None when it is not there or bd could not be asked."""
    try:
        return store.show(bead_id)
    except BdFailure:
        return None


def attempt(call: Any, *args: Any, **kw: Any) -> bool:
    """A bd write whose refusal changes nothing: True when it worked."""
    try:
        call(*args, **kw)
        return True
    except BdFailure:
        return False
