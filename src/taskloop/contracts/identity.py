"""Who a process acts as: the session and the bd actor name, built once at the edge from its Env (adapters/ident.py) and handed down."""
from typing import final

from taskloop.contracts.wire import Rec


@final
class Identity(Rec):
    """Who this process acts as, built once at the edge from its Env and handed down: the session and the bd actor name."""

    actor: str
    session: str = ""
