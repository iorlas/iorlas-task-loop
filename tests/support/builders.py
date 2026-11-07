"""`make_engine(**overrides)`: an Engine on fakes, the one way a test builds one.

Every seam has a default that is a fake (store, router, clock); `cfg=` passes through. Nothing here touches bd, delegate or
the wall clock; the engine still writes its own files under the test's XDG_CONFIG_HOME."""

from support.fakes import FakeBeadStore, FakeClock, FakeRouter
from support.spawn import port_git, real_spawner
from support.who import who
from taskloop.app.run import engine
from taskloop.app.run.state import state_names
from tlslots import config as wslots_config
from tlkernel.env import snapshot
from tlkernel.ids import BeadId
from tltestkit.cfgs import cfg_with


def make_engine(wt, bead="t-1", cfg=None, script=None, attrs=None, **seams):
    """An engine on `wt`. `cfg` is merged over the checkout's loaded config. Seams not given are fakes: `store`, `route`, `clock`;
    `attrs` sets engine state a test starts from (`{"plan_data": ..., "stage_tree": "old"}`) in place of `e.x = ...` lines."""
    c = wslots_config.load_cfg(str(wt), port_git())
    c = cfg_with(c, **(cfg or {}))
    seams.setdefault("store", FakeBeadStore())
    seams.setdefault("route", FakeRouter(script))
    seams.setdefault("clock", FakeClock())
    e = engine.Engine(BeadId(bead), str(wt), c, **seams, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who())
    amend_fields = {"amended": "amended", "old_plan": "old_plan", "amend_text": "text", "amend_why": "why"}
    for k, v in (attrs or {}).items():
        if k in amend_fields:
            setattr(e.amend, amend_fields[k], v)
            continue
        # checkpointed fields belong to the current run state; the review stage's fields are its own
        setattr(e.state if k in state_names() else e.review if k in vars(e.review) else e, k, v)
    return e
