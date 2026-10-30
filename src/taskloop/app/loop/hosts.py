"""Bead affinity at the pick (tl-7k8.8): a bead labelled `needs:<resource>` is taken only on a host that has the resource."""
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import EngineConfig, HostResources
from taskloop.contracts.loop import Skip
from taskloop.domain.checks import affinity


def skip_of(cfg: EngineConfig, rec: HostResources | None, b: Bead) -> Skip | None:
    """The typed skip of a bead whose needs label names a resource this host lacks, None when the host can run it."""
    lost = affinity.lacking(cfg, rec, affinity.needs_of(b.labels))
    if not lost:
        return None
    names = ", ".join(lost)
    return Skip(why=f"needs {names}, which this host does not have (host.json); a host that has it takes the bead", kind="needs")
