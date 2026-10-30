"""adapters/git.py on real git, in a throwaway repo: the same Git contract the gitsim runs."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401

from ports.git_contract import GitContract, contract
from taskloop.adapters.git import RealGit


@contract
class RealGitContract(GitContract, unittest.TestCase):
    def start(self) -> None:
        pass

    def make(self) -> RealGit:
        return RealGit()
