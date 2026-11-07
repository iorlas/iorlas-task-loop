"""Per-stage forward import closures, judged against the merge base with no stored baseline.

Every stage owns its files and reaches local modules through imports, including lazy and
TYPE_CHECKING imports. Distinct external top-level imports are the deterministic cause
of import-time cost; no noisy clock measurement is used. A rise needs a commit-message Ratchet-allow: closure +N reason.
"""
import ast
import sys
from collections.abc import Mapping
from pathlib import Path

from rules import ratchet_change

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dev"))
from importgraph import targets_of

TREES = ("src/taskloop", "packages/kernel/src/tlkernel", "packages/gate/src/tlgate",
         "packages/work/src/tlwork", "packages/slots/src/tlslots", "packages/asks/src/tlasks")


def stage_packages(packages):
    stages = sorted(name for name in packages if name.startswith("taskloop.app.") and name.count(".") == 2)
    if "tlgate" in packages:  # the gate is its package now; the shell's app/checks (step.py) is glue and keeps no budget of its own
        stages = [name for name in stages if name != "taskloop.app.checks"] + ["tlgate"]
    if "tlslots" in packages:
        stages = [name for name in stages if name != "tlslots"] + ["tlslots"]
    if "tlasks" in packages:
        stages = [name for name in stages if name != "taskloop.app." + "asks"] + ["tlasks"]
    for stage in ('review', 'plan'):
        if f'tlwork.{stage}' in packages:
            stages = [name for name in stages if name != 'taskloop.app.' + stage] + [f'tlwork.{stage}']
    return stages


def closures(texts: Mapping[str, str]) -> dict[str, int]:
    """Count reachable local files and distinct external module roots for each stage."""
    modules = {path.removeprefix("packages/kernel/").removeprefix("packages/gate/")
               .removeprefix("packages/work/").removeprefix("packages/slots/").removeprefix("packages/asks/").removeprefix("src/")
               .removesuffix(".py").replace("/", ".").removesuffix(".__init__"):
               path for path in texts if path.startswith(tuple(tree + "/" for tree in TREES)) and path.endswith(".py")}
    packages = {name for name, path in modules.items() if path.endswith("/__init__.py")}
    local_roots = {"taskloop", "tlkernel"} | {name.split(".")[0] for name in modules}
    external: dict[str, set[str]] = {}
    edges: dict[str, set[str]] = {}
    for name, path in modules.items():
        edges[name] = set()
        external[name] = set()
        for target in targets_of(name, ast.parse(texts[path]), packages):
            top = target.split(".")[0]
            if top not in local_roots:
                external[name].add(top)
            candidate = target
            while candidate:
                if candidate in modules:
                    edges[name].add(candidate)
                    break
                candidate = candidate.rpartition(".")[0]
    stages = stage_packages(packages)
    counts = {}
    for stage in stages:
        # a package's testing.py is its fakes for tests (the charter's third public name): not part of the production closure
        pending = [name for name in modules if (name == stage or name.startswith(stage + ".")) and not name.endswith(".testing")]
        reached: set[str] = set()
        while pending:
            name = pending.pop()
            if name not in reached:
                reached.add(name)
                pending.extend(edges[name] - reached)
        key = "checks" if stage == "tlgate" else ({"tlslots": "slots", "tlasks": "asks"}.get(stage, stage.rsplit(".", 1)[-1]))
        counts[key] = len(reached)
        counts[key + " (external modules)"] = len(set().union(*(external[name] for name in reached)))
    return counts


def problems(root: Path) -> list[str] | None:
    """Report stages whose closure grew beyond the change's total explicit allowance."""
    base = ratchet_change.merge_base(root)
    if base is None:
        return None
    paths = tuple(path for path in ratchet_change.git(root, "ls-tree", "-r", "--name-only", base, "--", *TREES).stdout.splitlines()
                  if path.endswith(".py"))
    before = closures({path: text for path, text in ratchet_change.texts_at(root, base, paths).items() if text is not None})
    after = closures({path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
                      for tree in TREES for path in (root / tree).rglob("*.py") if path.is_file()})
    up = ratchet_change.rises(before, after)
    if sum(up.values()) <= ratchet_change.allowed(root, base, "closure"):
        return []
    return [f"{stage.removesuffix(' (external modules)')}: +{n} external modules imported"
            if stage.endswith(" (external modules)") else f"{stage}: +{n} files in the forward closure"
            for stage, n in up.items()]
