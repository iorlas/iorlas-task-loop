"""Release spacing and explicit devbox acknowledgement, stored beside the persistent release clone."""
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.app.release import clone
from taskloop.app.release.shell import Abort
from taskloop.contracts.snapshots import ReleaseTrain
from taskloop.contracts.stores import JsonStore
from taskloop.contracts.wire import Refused

INTERVAL_S = 2 * 3600


def state(config: Path, url: str) -> JsonStore[ReleaseTrain]:
    return JsonStore(clone.clone_dir(config, url).with_suffix(".train.json"), ReleaseTrain)


def read(store: JsonStore[ReleaseTrain]) -> ReleaseTrain | None:
    try:
        return store.need()
    except Refused as e:
        raise Abort(str(e)) from None


def require_slot(config: Path, url: str, urgent: str, clock: Callable[[], float] = time.time) -> None:
    last = read(state(config, url))
    if last and clock() - last.at < INTERVAL_S and not urgent.strip():
        raise Abort("last release was less than 2 hours ago; use --urgent 'why' to override")


def shipped(config: Path, url: str, version: str, urgent: str, clock: Callable[[], float] = time.time) -> None:
    rec = ReleaseTrain(version=version, at=clock(), urgent=urgent)
    state(config, url).write(rec)
    ring_store(config, version).write(rec)


def ring_store(config: Path, version: str) -> JsonStore[ReleaseTrain]:
    if len(version.split(".")) != 3 or not all(p.isdigit() for p in version.split(".")):
        raise Abort("expected a release version MAJOR.MINOR.PATCH")
    return JsonStore(config / "release" / "rings" / (version + ".json"), ReleaseTrain)


def devbox_ok(config: Path, url: str, version: str) -> None:
    store = ring_store(config, version)
    rec = read(store)
    if not rec or rec.version != version:
        raise Abort(f"no release ring recorded for {version}")
    latest = read(state(config, url))
    store.write(rec.replace(ring="devbox-ok"))
    if latest and latest.version == version:
        state(config, url).write(latest.replace(ring="devbox-ok"))


def mac_pin_refusal(config: Path, version: str) -> str:
    try:
        rec = read(ring_store(config, version))
    except Abort as e:
        return str(e)
    ready = rec and rec.version == version and rec.ring == "devbox-ok"
    return "" if ready else f"refused: {version} needs devbox-ok before the Mac standing pin moves"
