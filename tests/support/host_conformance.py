"""A host Protocol (app/<stage>/host.py) against the object that is meant to satisfy it: the members it names that the object lacks.
The type checker proves the stage's code reads only the Protocol; this proves the real Engine, and any fake, still has every member."""
import typing
from typing import Any


def missing(host: Any, protocol: type) -> list[str]:
    """The members of `protocol` that `host` has no attribute for (instance state set in __init__ counts)."""
    return sorted(name for name in typing.get_protocol_members(protocol) if not hasattr(host, name))
