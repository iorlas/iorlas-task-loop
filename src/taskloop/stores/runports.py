"""RunPorts: the engine's own handles, one per capability a stage may ask for (docs/design/facts.md, tl-e5t0.28). It sits in the stores
layer because it holds the `Stores` bundle; the Protocols it is typed with, and `RunFacts`, are in contracts/runfacts.py."""
from dataclasses import dataclass

from taskloop.contracts.beadsport import Beads
from taskloop.contracts.env import Env
from taskloop.contracts.gitport import Git
from taskloop.contracts.ports import Clock
from taskloop.contracts.procport import Spawner
from taskloop.contracts.runfacts import CheckerPort, CheckLogPort, CheckpointsPort, Narrate, RepoKey, StepBook
from taskloop.stores.bundle import Stores


@dataclass(frozen=True, slots=True)
class RunPorts:
    """Frozen references to live objects: the data cannot be rebound, the objects still work."""

    clock: Clock
    env: Env
    git: Git
    spawner: Spawner
    steps: StepBook
    log: Narrate
    checklog: CheckLogPort
    store: Beads
    stores: Stores
    checkpoints: CheckpointsPort
    checker: CheckerPort
    repo: RepoKey
