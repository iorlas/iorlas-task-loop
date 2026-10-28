"""The suite's green, remembered by what it ran on: a tree hash and the exact command. A hit needs both identical; a wrong hit is
worse than a miss, so a red run never writes and nothing but a green one does."""
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

KEEP = 20


@dataclass(frozen=True)
class Green:
    tree: str
    command: str
    at: float


class SuiteCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _all(self) -> list[Green]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [Green(str(r["tree"]), str(r["command"]), float(r["at"])) for r in raw]
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def hit(self, tree: str, command: str) -> bool:
        return any(g.tree == tree and g.command == command for g in self._all())

    def record(self, tree: str, command: str, at: float) -> None:
        kept = [g for g in self._all() if not (g.tree == tree and g.command == command)]
        kept.append(Green(tree, command, at))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps([asdict(g) for g in kept[-KEEP:]]), encoding="utf-8")
        os.replace(tmp, self.path)
