"""Explicit matching-runtime rounds startup is the only authority to reopen a completed drain."""

from taskloop.drain.drain import Ports, drain, inspect
from taskloop.drain.models import BLOCKED, Boundary, Conclusion, Result, State


def restart(ports: Ports) -> Boundary | Result:
    before = ports.store.boundary()
    if before.state is State.OPEN:
        return before
    if before.state is State.DRAINING:
        return drain(ports)  # finish this boundary; this invocation does not reopen it
    observed = inspect(ports, before.generation)
    if observed.conclusion is not Conclusion.COMPLETE:
        return observed
    reopened = ports.store.reopen(before)
    return reopened or Result(conclusion=Conclusion.REFUSED, generation=before.generation, detail=BLOCKED)
