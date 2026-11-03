"""The owner's inbox on this machine: the AskStore of the config dir and the throttled passes over it (close the ask of a closed bead,
park the unanswered, shout about an answer no run used)."""
from collections.abc import Callable

from taskloop.adapters import ident
from taskloop.adapters.beadtools import bd_store
from taskloop.app.asks import setup_retry, sweeps
from taskloop.app.track.trail import now
from taskloop.contracts.bd_errors import BdCommandFailure
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.identity import Identity
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure
from taskloop.contracts.stores import AskStore


def store(home: ConfigDir) -> AskStore:
    return AskStore.at(home)


def sweep(which: str, who: Identity, home: ConfigDir, every: int = 600) -> list[str]:
    """The throttled sweeps over open asks (app/asks/sweeps.py): close those of closed or missing beads, park those unanswered in 3 days."""
    fn = sweeps.close_stale if which == "close" else sweeps.park_stale
    try:
        return list(fn(store(home), lambda repo: bd_store(who.actor, repo), home.ask_marker("swept" if which == "close" else "parked"),
                       now(),
            every))
    except BdCommandFailure:  # no bd on this machine
        return []


def sweep_asks(who: Identity, home: ConfigDir, say: Callable[[str], None] = print, cfg: EngineConfig | None = None,
               repo: str = "") -> None:
    """The loop's pass over asks: close the stale, park the unanswered, and shout about an answer no run used for 30 minutes (an engine
    fault, not the owner's). The three are throttled by marker files, so any caller may call it as often as it likes."""
    sweep("close", who, home)
    sweep("park", who, home)
    if cfg:
        asks = store(home)
        for ask in asks.live():
            if not repo or ask.repo != repo:
                continue
            try:
                setup_retry.retry_setup(asks, bd_store(who.actor, ask.repo), ask.bead, ident.plugin_version(), now(), cfg)
            except BdFailure:
                continue
        sweeps.reask_orphans(store(home), bd_store(who.actor), home.ask_marker("orphans"), now(), cfg.pick_label or "",
            cfg.needs_info_label or "", say)
    sweeps.shout(store(home), home.ask_marker("unused"), now(), say)
