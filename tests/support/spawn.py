"""The Spawner and the Git a test hands to code that takes one: the real adapters on the process's environment (a logic test's children are
procsim's fakes and its git the gitsim, a real test's are real)."""

from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from tlkernel.env import snapshot
from tlkernel.gitport import Git
from tlkernel.procport import Spawner


def real_spawner() -> Spawner:
    return RealSpawner(snapshot())


def port_git() -> Git:
    return RealGit(snapshot())
