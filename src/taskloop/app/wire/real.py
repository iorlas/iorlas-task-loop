"""The real ports, built at the edge (a verb's entry point, a script's main) and handed down: nothing below it builds its own."""
from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.contracts.env import Env
from taskloop.contracts.ports import Git, Spawner


def spawner(env: Env) -> Spawner:
    """The real Spawner on `env`, the environment taken at the edge. Only an edge builds one (tests/rules/test_env_below_edge.py)."""
    return RealSpawner(env)


def git() -> Git:
    return RealGit()
