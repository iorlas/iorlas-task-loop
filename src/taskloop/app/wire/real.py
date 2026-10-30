"""The real ports, built at the edge (a verb's entry point, a script's main) and handed down: nothing below it builds its own."""
from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.contracts import env as penv
from taskloop.contracts.env import Env
from taskloop.contracts.ports import Git, Spawner


def spawner(env: Env | None = None) -> Spawner:
    """The real Spawner on `env`, the environment taken at the edge. No `env`: the process's own, taken now (the rule test
    tests/rules/test_env_below_edge.py counts every call that leaves it out; it may only shrink)."""
    return RealSpawner(penv.snapshot() if env is None else env)


def git() -> Git:
    return RealGit()
