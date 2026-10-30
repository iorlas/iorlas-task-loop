"""`make_engine(**overrides)`: an Engine on fakes, the one way a test builds one.

Every seam has a default that is a fake (store, router, clock); `git=` and `cfg=` pass through. Nothing here touches bd, delegate or
the wall clock; the engine still writes its own files under the test's XDG_CONFIG_HOME."""
import shlex

from support.fakes import FakeBeadStore, FakeClock, FakeRouter
from taskloop.app.run import engine
from taskloop.app.wire import slots as wslots
from taskloop.contracts import wire
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.env import snapshot
from taskloop.contracts.ids import BeadId


def make_engine(wt, bead="t-1", cfg=None, script=None, attrs=None, **seams):
    """An engine on `wt`. `cfg` is merged over the checkout's loaded config. Seams not given are fakes: `store`, `route`, `clock`;
    `git` is the engine's own (the real repo) unless given. The fakes are on the engine as `.store`, `.router`, `.clock`.
    `attrs` sets engine state a test starts from (`{"plan_data": ..., "stage_tree": "old"}`) in place of `e.x = ...` lines."""
    c = wslots.load_cfg(str(wt))
    c = cfg_with(c, **(cfg or {}))
    seams.setdefault("store", FakeBeadStore())
    seams.setdefault("route", FakeRouter(script))
    seams.setdefault("clock", FakeClock())
    e = engine.Engine(BeadId(bead), str(wt), c, **seams, env=snapshot())
    for k, v in (attrs or {}).items():
        setattr(e, k, v)
    return e


def argv_cfg(cfg):
    """An engine config as a test writes it (a command as one plain string, `cmd` for a check) with each command split into the argv
    the profile holds (shlex, no shell). A command that needs a shell is written as a list by the test."""
    out = dict(cfg)
    if isinstance(out.get("land"), str):
        out["land"] = shlex.split(out["land"])
    if "checks" in out:
        out["checks"] = [
            dict(x, argv=shlex.split(x.pop("cmd"))) if isinstance(x, dict) and "cmd" in x else x for x in map(dict, out["checks"])
        ]
    gate = out.pop("gate", None)  # a test writes the gate as one command (a string or an argv): the profile holds it as a gate check
    if gate:
        argv = shlex.split(gate) if isinstance(gate, str) else gate
        out["checks"] = [*out.get("checks", []), {"id": "gate", "argv": argv, "run": "gate"}]
    for n, only in enumerate(out.pop("gate_only", [])):  # a command only the gate runs
        spec = only if isinstance(only, dict) else {"cmd": only}
        argv = shlex.split(spec["cmd"]) if "cmd" in spec else spec["argv"]
        out["checks"] = [*out.get("checks", []), {"id": f"gate-only-{n}", "argv": argv, "run": "gate", "why": spec.get("why", "")}]
    return out


def cfg_with(base=None, **changes):
    """An EngineConfig: `base` (default: all defaults) with `changes` over it. Values may be plain JSON (a `checks` list of dicts)."""
    d = wire.dump(base or EngineConfig())
    gated = "gate" in changes or "gate_only" in changes
    explicit = "checks" in changes
    changes = argv_cfg(changes)
    if gated and not explicit:  # a new gate replaces the base's gate steps; the base's other checks stay unless the test lists its own
        keep = [c for c in d.get("checks", []) if not (c["id"] == "gate" or c["id"].startswith("gate-only-"))]
        changes["checks"] = keep + changes.get("checks", [])
    d["base_red"] = False  # an always-red command in a test would otherwise be asked again on the base; the tests of that ask turn it on
    d.update(changes)
    return wire.load(EngineConfig, d)
