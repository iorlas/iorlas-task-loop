"""Bead affinity (tl-7k8.8): a label `needs:<resource>` says the bead runs only on a host that has the resource. Pure.

The author may write the label by hand; the engine only ever adds it (at the plan and at the land) and never removes one."""
from collections.abc import Iterable

from taskloop.contracts.checks import Check
from taskloop.contracts.config import EngineConfig, HostResources
from taskloop.domain.checks.inputs import touched

PREFIX = "needs:"


def label(resource: str) -> str:
    return PREFIX + resource


def needs_of(labels: Iterable[str]) -> list[str]:
    """The resources a bead's labels say it needs, in label order."""
    return [x[len(PREFIX):] for x in labels if x.startswith(PREFIX) and len(x) > len(PREFIX)]


def have(cfg: EngineConfig, rec: HostResources | None) -> set[str]:
    """The resources this host has: host.json's list; no file: every resource the repo declares."""
    return set(cfg.resources) if rec is None else set(rec.resources)


def lacking(cfg: EngineConfig, rec: HostResources | None, needs: Iterable[str]) -> list[str]:
    """The declared resources among `needs` this host does not have (a need nobody declared is no resource: it never holds a bead back)."""
    mine = have(cfg, rec)
    return [n for n in dict.fromkeys(needs) if n in cfg.resources and n not in mine]


def planned(checks: Iterable[Check], changed: Iterable[str], cfg: EngineConfig, rec: HostResources | None) -> list[str]:
    """The resources this host lacks that a check hit by `changed` needs, sorted."""
    paths = list(changed)
    hit = [n for c in checks if touched(c, paths) for n in c.needs]
    return sorted(lacking(cfg, rec, hit))
