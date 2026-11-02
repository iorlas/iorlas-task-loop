"""Unexpected late engine failures park accepted work at its existing cursor."""
import traceback
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING

from taskloop.contracts.kinds import Kind
from taskloop.domain import outcome as oc

if TYPE_CHECKING:
    from taskloop.app.run.engine import Engine


def parked_crash(e: Engine, step: str, err: Exception) -> oc.RunOutcome:
    frames = traceback.extract_tb(err.__traceback__)
    site = f"{Path(frames[-1].filename).name}:{frames[-1].name}:{frames[-1].lineno}" if frames else "unknown"
    e.crash_site = site
    e.crash_fingerprint = sha1(f"{type(err).__name__}:{site}".encode()).hexdigest()[:12]
    e.fp = e.crash_fingerprint
    why = f"{step} crashed: {type(err).__name__}: {err}"[:200]
    e.kind, e.why = Kind.ENGINE_CRASH, why
    e.pause_reason = e.kind.value
    e.log.warn(why + "\n" + "".join(traceback.format_exception(err)))
    return oc.make(e.kind, why)
