"""Unexpected late engine failures park accepted work at its existing cursor."""
import traceback
from typing import TYPE_CHECKING

from taskloop.contracts.kinds import Kind
from taskloop.domain import outcome as oc

if TYPE_CHECKING:
    from taskloop.app.run.engine import Engine


def parked_crash(e: Engine, step: str, err: Exception) -> oc.RunOutcome:
    why = f"{step} crashed: {type(err).__name__}: {err}"[:200]
    e.kind, e.why = Kind.ENGINE_CRASH, why
    e.pause_reason = e.kind.value
    e.log.warn(why + "\n" + "".join(traceback.format_exception(err)))
    return oc.make(e.kind, why)
