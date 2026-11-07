"""Late failures retain accepted work: refusals ask the owner, unexpected crashes retry the existing cursor."""
import traceback
from hashlib import sha1
from pathlib import Path

from tlkernel.kinds import Kind

from taskloop.app.run.host import RunHost
from taskloop.domain import outcome as oc


def parked_crash(e: RunHost, step: str, err: Exception) -> oc.RunOutcome:
    if isinstance(err, ValueError):
        why = f"{step} refused: {type(err).__name__}: {err}"
        e.kind, e.why = Kind.PAUSE_LANE, why
        e.pause_reason, e.pause_producer = "stage_refused", "engine"
        e.crash_fingerprint, e.fp = "", ""
        e.log.warn(why + "\n" + "".join(traceback.format_exception(err)))
        return oc.make(e.kind, why)
    frames = traceback.extract_tb(err.__traceback__)
    site = f"{Path(frames[-1].filename).name}:{frames[-1].name}:{frames[-1].lineno}" if frames else "unknown"
    e.crash_site = site
    e.crash_fingerprint = sha1(f"{type(err).__name__}:{site}".encode()).hexdigest()[:12]
    e.fp = e.crash_fingerprint
    why = f"{step} crashed: {type(err).__name__}: {err}"[:200]
    e.kind, e.why = Kind.ENGINE_CRASH, why
    e.pause_reason = e.kind.value
    e.pause_producer = "engine"
    e.log.warn(why + "\n" + "".join(traceback.format_exception(err)))
    return oc.make(e.kind, why)
