"""A GateHost without an Engine (app/land/gate.py GateHost): the checks' FakeCheckHost plus what only the gate reads of the engine, the
land's unsaved state and the stops (docs/design/b-land.md, slice 3). A land gate test on this host reaches the gate and the check runner,
not app/run/engine.py."""
from pathlib import Path
from typing import Any

from support.check_host import CheckHostCase, FakeCheckHost
from support.memstores import fake_stores
from support.who import who
from taskloop.app.land.host import LandState
from tlkernel.config import EngineConfig
from tlkernel.paths import ConfigDir
from tlkernel.ports import Clock
from tlpipeline.blocked import Blocked, blocked_for
from tltestkit.cfgs import cfg_with


class GateRig(FakeCheckHost):
    def __init__(self, wt: Path, cfg: EngineConfig, home: ConfigDir, **kw: Any) -> None:
        super().__init__(wt, cfg, home, **kw)
        self.land_state = LandState()

    def blocked_for(self, why: str, kind: str, **kw: Any) -> Blocked:
        return blocked_for(why, kind, **kw)

    def move_host(self, needs: list[str], why: str) -> Blocked:
        self.moved = [*getattr(self, "moved", []), *needs]
        return blocked_for(why, "PAUSE_MOVED")


class GateCase(CheckHostCase):
    """A land gate test: the slot's world and a GateRig over it. `checks_engine(**cfg)` keeps the name of the EngineTest helper."""

    def checks_engine(self, attrs: Any = None, *, clock: Clock | None = None, **cfg: Any) -> GateRig:
        stores = self.__dict__.setdefault("_check_stores", fake_stores())
        n = self.__dict__["_check_hosts"] = self.__dict__.get("_check_hosts", -1) + 1
        host = GateRig(self.wt, cfg_with(EngineConfig(), **cfg), who().config, stores=stores, nth=n, clock=clock)
        for k, v in (attrs or {}).items():
            setattr(host, k, v)
        return host
