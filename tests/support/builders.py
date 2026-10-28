"""`make_engine(**overrides)`: an Engine on fakes, the one way a test builds one.

Every seam has a default that is a fake (store, router, clock); `git=` and `cfg=` pass through. Nothing here touches bd, delegate or
the wall clock; the engine still writes its own files under the test's XDG_CONFIG_HOME."""
import engine
from taskloop.contracts.codec import from_json, to_json
from taskloop.contracts.config import EngineConfig

from support.fakes import FakeBeadStore, FakeClock, FakeRouter


def make_engine(wt, bead="t-1", cfg=None, script=None, attrs=None, **seams):
    """An engine on `wt`. `cfg` is merged over the checkout's loaded config. Seams not given are fakes: `store`, `route`, `clock`;
    `git` is the engine's own (the real repo) unless given. The fakes are on the engine as `.store`, `.router`, `.clock`.
    `attrs` sets engine state a test starts from (`{"plan_data": ..., "stage_tree": "old"}`) in place of `e.x = ...` lines."""
    c = engine.load_cfg(str(wt))
    c = cfg_with(c, **(cfg or {}))
    seams.setdefault("store", FakeBeadStore())
    seams.setdefault("route", FakeRouter(script))
    seams.setdefault("clock", FakeClock())
    e = engine.Engine(bead, str(wt), c, **seams)
    for k, v in (attrs or {}).items():
        setattr(e, k, v)
    return e


def cfg_with(base=None, **changes):
    """An EngineConfig: `base` (default: all defaults) with `changes` over it. Values may be plain JSON (a `checks` list of dicts)."""
    d = to_json(base or EngineConfig())
    d["base_red"] = False  # an always-red command in a test would otherwise be asked again on the base; the tests of that ask turn it on
    d.update(changes)
    return from_json(EngineConfig, d)
