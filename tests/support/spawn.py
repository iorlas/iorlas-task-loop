"""The Spawner a test hands to code that takes one: the real adapter on the process's environment (a logic test's children are procsim's
fakes, a real test's are real)."""
from taskloop.adapters.spawner import RealSpawner
from taskloop.contracts.env import snapshot
from taskloop.contracts.ports import Spawner


def real_spawner() -> Spawner:
    return RealSpawner(snapshot())
