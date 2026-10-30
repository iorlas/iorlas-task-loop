"""The real ports, built at the edge (a verb's entry point, a script's main) and handed down: nothing below it builds its own."""
from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.contracts.ports import Git, Spawner


def spawner() -> Spawner:
    return RealSpawner()


def git() -> Git:
    return RealGit()
