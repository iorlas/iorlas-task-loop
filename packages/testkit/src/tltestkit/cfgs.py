"""The config a test writes: `cfg_with`, `argv_cfg`, `plan_of`. Imports no engine, so such a test does not reach the shell."""
import shlex
from collections.abc import Mapping
from typing import Any

from tlkernel import wire
from tlkernel.config import EngineConfig
from tlkernel.plancheck import PlanData

# the patterns a Unity consumer's profile sets; the engine has none of its own
# the patterns a Unity consumer's profile sets; the engine has none of its own
PROFILE_PATTERNS = {
    "queued_match": "(?i)unity",
    "lock_fail": "(?i)another Unity instance|Multiple Unity instances|It looks like another Unity instance is running",
    "slow_cmd": r"(?i)(?<![a-z])(unity|play|test[-_]all|check|build|dotnet)",
    "project_log": "client/Logs/unity-project-files.log",
}


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
    d.update({k: v for k, v in PROFILE_PATTERNS.items() if not d.get(k)})
    d["base_red"] = False  # an always-red command in a test would otherwise be asked again on the base; the tests of that ask turn it on
    d.update(changes)
    return wire.load(EngineConfig, d)


def plan_of(raw: Mapping[str, Any]) -> PlanData:
    """A plan a test writes as a plain dict, as the engine keeps it (a stage may name just its goal and checks here)."""
    return PlanData(**raw)
