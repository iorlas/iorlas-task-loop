"""adapters/git.py: the shared Git contract on the gitsim (logic: no process), plus the classifier of git's words."""
import contextlib
import unittest

import support.paths  # noqa: F401

# isort: split
from support import gitsim

from ports.git_contract import GitContract, contract
from ports.git_contract_land import LandContract
from taskloop.adapters.git import RealGit
from taskloop.contracts.env import snapshot


@contract
class GitSimContract(GitContract, LandContract, unittest.TestCase):
    def start(self) -> None:
        gitsim.reset()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        sim = gitsim.Sim(self)
        sim.install(stack)
        self.addCleanup(sim.check)

    def make(self) -> RealGit:
        return RealGit(snapshot())
