"""The families delegate may pick for one bead's worker call: the profile pin, a bead label, or the warm second family."""

from collections.abc import Collection

from taskloop.contracts.config import EngineConfig
from taskloop.contracts.plancheck import PlanData
from taskloop.domain.lanes import pin


def pinned(cfg: EngineConfig, bead: str, plan: PlanData | None, labels: Collection[str], role: str) -> list[str]:
    """What `--only-family` carries on a call of `role`. The second family needs a plan (light = one stage, no host grant)."""
    light = pin.is_light(len((plan or {}).get("stages") or []), bool(cfg.writer_exec_allow))
    return pin.for_role(role, pin.families(cfg.writer_family, labels, pin.Warm(cfg.second_writer_family, bead, light)))


def warm(cfg: EngineConfig, bead: str, plan: PlanData | None, labels: Collection[str]) -> str:
    """The second family when this bead is the chosen one (it pins the worker), else ''."""
    on = pinned(cfg, bead, plan, labels, pin.PINNED_ROLE)
    return on[0] if on and on != pin.families(cfg.writer_family, labels) else ""
