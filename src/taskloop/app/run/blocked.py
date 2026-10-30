"""The stop a step ends with: what the engine does at the close follows from its kind."""
from typing import Any

from taskloop.domain import outcome as oc
from taskloop.domain.asks.spec import AskSpec


class Blocked(Exception):
    """A stop. kind: the outcome.Kind that says what the engine does at the close (POLICY). spec: the AskSpec of an ask kind (what
    the owner is asked, built from facts at the raise site); a stop that is no ask carries none."""

    def __init__(self, why: str, spec: AskSpec | None = None, *, kind: oc.Kind) -> None:
        super().__init__(why)
        if (kind in oc.ASKS) != (spec is not None):  # an ask with no spec (or a spec on no ask) is the engine's own fault
            first = why.splitlines()[0][:200] if why else ""
            why, spec, kind = f"failed: ask_lint: the stop carries no ask or an ask it cannot be ({first})", None, oc.Kind.FAULT_ENGINE
        self.why, self.spec, self.kind = why, spec, kind
        self.stop: Any = None

    @property
    def outcome(self) -> oc.RunOutcome:
        return oc.make(self.kind, self.why, spec=self.spec)


class FixFailed(Blocked):
    """A conflict fix round that could not finish (no rounds left, or the rebase would not continue): a resume salvage starts again."""


def blocked_for(why: str, kind: str, stop: Any = None, spec: AskSpec | None = None, fix: bool = False) -> Blocked:
    """The Blocked a step ends with: `kind` is an outcome.Kind name; `stop` the stop that decided it; `spec` the ask it carries;
    `fix`: a conflict fix round that could not finish (a resume salvage starts again)."""
    err = (FixFailed if fix else Blocked)(why, spec, kind=oc.Kind[kind])
    err.stop = stop
    return err
