"""Late failures retain accepted work: refusals ask the owner, unexpected crashes retry the existing cursor."""
import traceback
from hashlib import sha1
from pathlib import Path
from typing import Protocol

from tlkernel.kinds import Kind

from taskloop.domain import outcome as oc
from taskloop.domain.lanes.pause_reasons import Producer


class CrashLog(Protocol):
    def warn(self, text: str) -> object: ...


class CrashHost(Protocol):
    kind: Kind
    why: str
    pause_reason: str
    pause_producer: Producer
    crash_fingerprint: str
    fp: str
    crash_site: str

    @property
    def log(self) -> CrashLog: ...


def parked_crash(host: CrashHost, step: str, err: Exception) -> oc.RunOutcome:
    if isinstance(err, ValueError):
        why = f"{step} refused: {type(err).__name__}: {err}"
        host.kind, host.why = Kind.PAUSE_LANE, why
        host.pause_reason, host.pause_producer = "stage_refused", "engine"
        host.crash_fingerprint, host.fp = "", ""
        host.log.warn(why + "\n" + "".join(traceback.format_exception(err)))
        return oc.make(host.kind, why)
    frames = traceback.extract_tb(err.__traceback__)
    site = f"{Path(frames[-1].filename).name}:{frames[-1].name}:{frames[-1].lineno}" if frames else "unknown"
    host.crash_site = site
    host.crash_fingerprint = sha1(f"{type(err).__name__}:{site}".encode()).hexdigest()[:12]
    host.fp = host.crash_fingerprint
    why = f"{step} crashed: {type(err).__name__}: {err}"[:200]
    host.kind, host.why = Kind.ENGINE_CRASH, why
    host.pause_reason = host.kind.value
    host.pause_producer = "engine"
    host.log.warn(why + "\n" + "".join(traceback.format_exception(err)))
    return oc.make(host.kind, why)
