"""Per-stage forward import closures, judged against the merge base with no stored baseline.

Every stage owns its files and reaches local modules through imports, including lazy and
TYPE_CHECKING imports. A rise needs a commit-message Ratchet-allow: closure +N reason.
"""
import ast
import sys
from collections.abc import Mapping
from pathlib import Path

from rules import ratchet_change

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dev"))
from importgraph import targets_of


def closures(texts: Mapping[str, str]) -> dict[str, int]:
    """Count each stage's own modules and all modules reachable through local imports."""
    modules = {path.removeprefix("src/").removesuffix(".py").replace("/", ".").removesuffix(".__init__"): path
               for path in texts if path.startswith("src/taskloop/") and path.endswith(".py")}
    packages = {name for name, path in modules.items() if path.endswith("/__init__.py")}
    edges: dict[str, set[str]] = {}
    for name, path in modules.items():
        edges[name] = set()
        for target in targets_of(name, ast.parse(texts[path]), packages):
            candidate = target
            while candidate:
                if candidate in modules:
                    edges[name].add(candidate)
                    break
                candidate = candidate.rpartition(".")[0]
    stages = sorted(name for name in packages if name.startswith("taskloop.app.") and name.count(".") == 2)
    counts = {}
    for stage in stages:
        pending = [name for name in modules if name == stage or name.startswith(stage + ".")]
        reached: set[str] = set()
        while pending:
            name = pending.pop()
            if name not in reached:
                reached.add(name)
                pending.extend(edges[name] - reached)
        counts[stage.rsplit(".", 1)[1]] = len(reached)
    return counts


def problems(root: Path) -> list[str] | None:
    """Report stages whose closure grew beyond the change's total explicit allowance."""
    base = ratchet_change.merge_base(root)
    if base is None:
        return None
    paths = tuple(path for path in ratchet_change.git(root, "ls-tree", "-r", "--name-only", base, "--", "src/taskloop").stdout.splitlines()
                  if path.endswith(".py"))
    before = closures({path: text for path, text in ratchet_change.texts_at(root, base, paths).items() if text is not None})
    after = closures({path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
                      for path in (root / "src/taskloop").rglob("*.py") if path.is_file()})
    up = ratchet_change.rises(before, after)
    if sum(up.values()) <= ratchet_change.allowed(root, base, "closure"):
        return []
    return [f"{stage}: +{n} files in the forward closure" for stage, n in up.items()]
