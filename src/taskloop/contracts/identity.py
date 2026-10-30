"""Who a process acts as and where its state lives: the session, the bd actor name and the task-loop config dir, built once at the edge
from its Env (adapters/ident.py) and handed down."""
from typing import final

from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.wire import Rec


@final
class Identity(Rec):
    """Who this process acts as, built once at the edge from its Env and handed down: the session, the bd actor name, and the root of the
    config dir its records are kept in (XDG_CONFIG_HOME of that Env)."""

    actor: str
    home: str
    session: str = ""

    @property
    def config(self) -> ConfigDir:
        return ConfigDir(self.home)
