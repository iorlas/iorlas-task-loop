"""The owner's inbox on this machine: the AskStore of the config dir and the throttled passes over it (close the ask of a closed bead,
park the unanswered, shout about an answer no run used)."""
from collections.abc import Callable

from taskloop.adapters.beadtools import bd_store
from taskloop.adapters.ident import config_dir
from taskloop.app.asks import sweeps
from taskloop.app.track.trail import now
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore


def store() -> AskStore:
    return AskStore.at(ConfigDir(config_dir()))


def sweep(which: str, every: int = 600) -> list[str]:
    """The throttled sweeps over open asks (app/asks/sweeps.py): close those of closed or missing beads, park those unanswered in 3 days."""
    cfg = ConfigDir(config_dir())
    fn = sweeps.close_stale if which == "close" else sweeps.park_stale
    try:
        return list(fn(store(), bd_store, cfg.ask_marker("swept" if which == "close" else "parked"), now(), every))
    except SystemExit:  # no bd on this machine
        return []


def sweep_asks(say: Callable[[str], None] = print, cfg: EngineConfig | None = None) -> None:
    """The loop's pass over asks: close the stale, park the unanswered, and shout about an answer no run used for 30 minutes (an engine
    fault, not the owner's). The three are throttled by marker files, so any caller may call it as often as it likes."""
    sweep("close")
    sweep("park")
    marks = ConfigDir(config_dir())
    if cfg:
        sweeps.reask_orphans(store(), bd_store(), marks.ask_marker("orphans"), now(), cfg.pick_label or "", cfg.needs_info_label or "", say)
    sweeps.shout(store(), marks.ask_marker("unused"), now(), say)
