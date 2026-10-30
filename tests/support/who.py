"""The Identity a test hands to code that takes one: built from the process environment at the moment of the call, as the edge builds it
(a test that sets CLAUDE_CODE_SESSION_ID or TASK_LOOP_ACTOR gets that session and actor).

A fake tracker answers as the actor of the call it serves (`acting`): bd names the claimer in its argv, as the real bd does.

A test of racing sessions sets PER_THREAD: each thread is then one session, its actor the name in the dict or else the thread's name."""
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from taskloop.adapters.ident import config_dir, identity
from taskloop.contracts.env import snapshot
from taskloop.contracts.identity import Identity

PER_THREAD: dict[str, str] | None = None
_serving = threading.local()


@contextmanager
def acting(actor: str) -> Iterator[None]:
    before = getattr(_serving, "actor", None)
    _serving.actor = actor
    try:
        yield
    finally:
        _serving.actor = before


def who() -> Identity:
    if getattr(_serving, "actor", None):
        return Identity(actor=_serving.actor, home=str(config_dir(snapshot())))
    if PER_THREAD is not None:
        name = threading.current_thread().name
        return Identity(actor=PER_THREAD.get(name, name), home=str(config_dir(snapshot())))
    return identity(snapshot())
