"""Bind the owner's inbox and its machine sweeps to the shell services."""
from collections.abc import Callable
from typing import Concatenate

from tlasks import sweeps
from tlasks.sweeps import SweepHost
from tlkernel.askstore import AskStore
from tlkernel.config import EngineConfig
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.paths import ConfigDir

from taskloop.adapters import beadtools, ident
from taskloop.adapters.beadtools import bd_store
from taskloop.app.land import forge
from taskloop.app.land.cmds import Runs
from taskloop.app.track.trail import now
from taskloop.stores.real import real_stores


def store(home: ConfigDir) -> AskStore:
    return real_stores(home).asks


def host() -> SweepHost:
    return SweepHost(lambda actor, repo: bd_store(actor, repo), beadtools.peek, ident.hostname, store, now, ident.plugin_version)


def bound[**P, R](fn: Callable[Concatenate[SweepHost, P], R]) -> Callable[P, R]:
    def call(*args: P.args, **kwargs: P.kwargs) -> R:
        return fn(host(), *args, **kwargs)
    return call


sweep = bound(sweeps.sweep)
sweep_asks = bound(sweeps.sweep_asks)


def wake_prs(who: Identity, home: ConfigDir, spawner: Runs, cfg: EngineConfig, repo: str, every: int = 120) -> list[BeadId]:
    return sweeps.wake_prs(host(), who, home, lambda n: forge.peek(spawner, repo, n), cfg, repo, every)
