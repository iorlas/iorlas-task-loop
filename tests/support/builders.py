"""`make_engine(**overrides)`: an Engine on fakes, the one way a test builds one.

Every seam has a default that is a fake (store, router, clock); `cfg=` passes through. Nothing here touches bd, delegate or
the wall clock; the engine still writes its own files under the test's XDG_CONFIG_HOME."""

from support.cfgs import cfg_with
from support.fakes import FakeBeadStore, FakeClock, FakeRouter
from support.spawn import port_git, real_spawner
from support.who import who
from taskloop.app.look.state import LOOK_FIELDS
from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId


def make_engine(wt, bead="t-1", cfg=None, script=None, attrs=None, **seams):
    """An engine on `wt`. `cfg` is merged over the checkout's loaded config. Seams not given are fakes: `store`, `route`, `clock`;
    `attrs` sets engine state a test starts from (`{"plan_data": ..., "stage_tree": "old"}`) in place of `e.x = ...` lines."""
    c = wslots.load_cfg(str(wt), port_git())
    c = cfg_with(c, **(cfg or {}))
    seams.setdefault("store", FakeBeadStore())
    seams.setdefault("route", FakeRouter(script))
    seams.setdefault("clock", FakeClock())
    e = engine.Engine(BeadId(bead), str(wt), c, **seams, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who())
    for k, v in (attrs or {}).items():
        setattr(e.state if k in LOOK_FIELDS else e, k, v)  # the look stage's checkpointed fields are the run state's
    return e
