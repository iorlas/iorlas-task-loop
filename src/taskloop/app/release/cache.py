"""The suite's green, remembered by what it ran on: a tree hash and the exact command. A hit needs both identical; a wrong hit is
worse than a miss, so a red run never writes and nothing but a green one does."""
from taskloop.contracts.guard import guard
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.snapshots import GreenRun, SuiteGreens
from taskloop.contracts.stores import SuiteGreenStore

KEEP = 20


class SuiteCache:
    def __init__(self, cfg: ConfigDir) -> None:
        self.docs = SuiteGreenStore(cfg)

    def _all(self) -> list[GreenRun]:
        found = self.docs.read()
        return found.greens if found else []

    def hit(self, tree: str, command: str) -> bool:
        return any(g.tree == tree and g.command == command for g in self._all())

    def record(self, tree: str, command: str, at: float) -> None:
        with guard(self.docs.path.with_name(self.docs.path.name + ".lock")):  # read, add, write as one step
            kept = [g for g in self._all() if not (g.tree == tree and g.command == command)]
            kept.append(GreenRun(tree=tree, command=command, at=at))
            self.docs.write(SuiteGreens(greens=kept[-KEEP:]))
