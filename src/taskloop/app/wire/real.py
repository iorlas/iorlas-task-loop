"""The real ports, built at the edge (a verb's entry point, a script's main) and handed down: nothing below it builds its own."""
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.procport import Spawner

from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner


def spawner(env: Env) -> Spawner:
    """The real Spawner on `env`, the environment taken at the edge. Only an edge builds one (tests/rules/test_env_below_edge.py)."""
    return RealSpawner(env)


def git(env: Env) -> Git:
    """The real Git port on `env`, the environment taken at the edge."""
    return RealGit(env)
