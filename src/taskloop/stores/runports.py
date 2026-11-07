"""RunPorts: the engine's own handles, one per capability a stage may ask for (docs/design/facts.md, tl-e5t0.28). It sits in the stores
layer because it holds the `Stores` bundle; the Protocols it is typed with, and `RunFacts`, are in contracts/stagefacts.py."""
from dataclasses import dataclass

from taskloop.stores.bundle import Stores
from tlkernel.beadsport import Beads
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.ports import Clock
from tlkernel.procport import Spawner
from tlkernel.stagefacts import CheckerPort, CheckLogPort, CheckpointsPort, RepoKey, RunLogPort, StepBook


@dataclass(frozen=True, slots=True)
class RunPorts:
    """Frozen references to live objects: the data cannot be rebound, the objects still work."""

    clock: Clock
    env: Env
    git: Git
    spawner: Spawner
    steps: StepBook
    log: RunLogPort
    checklog: CheckLogPort
    store: Beads
    stores: Stores
    checkpoints: CheckpointsPort
    checker: CheckerPort
    repo: RepoKey
