"""The stop a step ends with: what the engine does at the close follows from its kind."""
from typing import Any

from taskloop.domain import outcome as oc


class Blocked(Exception):
    """A stop. kind: the outcome.Kind that says what the engine does at the close (POLICY). spec: the AskSpec of an ask kind (what
    the owner is asked, built from facts at the raise site); a stop that is no ask carries none."""

    def __init__(self, why: str, spec: Any = None, kind: Any = None) -> None:
        super().__init__(why)
        self.why, self.spec, self.kind = why, spec, kind
        self.stop: Any = None


class FixFailed(Blocked):
    """A conflict fix round that could not finish (no rounds left, or the rebase would not continue): a resume salvage starts again."""


def blocked_for(why: str, kind: str, stop: Any = None, spec: Any = None, fix: bool = False) -> Blocked:
    """The Blocked a step ends with: `kind` is an outcome.Kind name; `stop` the stop that decided it; `spec` the ask it carries;
    `fix`: a conflict fix round that could not finish (a resume salvage starts again)."""
    err = (FixFailed if fix else Blocked)(why, spec, kind=oc.Kind[kind])
    err.stop = stop
    return err
