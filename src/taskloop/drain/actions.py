"""Short durable authorizations around synchronous work, outside every external IO call."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from taskloop.drain.models import BLOCKED, ActionKind, Identity
from taskloop.drain.observe import identity
from taskloop.drain.store import Begin, Connect, DrainStore


class Connection(Protocol):
    connect: Connect
    begin: Begin


class Fenced(Exception):
    def __init__(self) -> None:
        super().__init__(BLOCKED)


class Unobservable(Exception):
    pass


@dataclass
class Call:
    resolved: bool = True


@contextmanager
def operation(
    store: Connection,
    kind: ActionKind,
    *,
    subject: str = "",
    generation: int | None = None,
    backlog: str = "",
    checkout: str = "",
    existing: Callable[[Identity], bool] = lambda _identity: False,
    me: Callable[[], Identity | None] = identity,
) -> Generator[Call]:
    owner = me()
    if owner is None:
        raise Unobservable("The calling process's identity is unavailable")
    drain = DrainStore(store.connect)
    call = Call()
    if kind is ActionKind.FINALIZE and (existing(owner) or drain.owns_active(owner)):
        yield call  # already recorded by the entry or its enclosing synchronous operation
        return
    action = drain.authorize(kind, owner, subject=subject, generation=generation, backlog=backlog, checkout=checkout)
    if action is None:
        raise Fenced()
    yield call
    if call.resolved:
        drain.finish(action)
    else:
        drain.uncertain(action)
