"""Application slice imports and domain effects expressed as AST invariants."""
import ast
from typing import Final

from importgraph import bindings, qualified

# The former per-slice deny contracts, expressed once as allowed direct imports.
SLICE_IMPORTS: Final = {
    "artifacts": frozenset(),
    "asks": frozenset(),
    "checks": frozenset(),
    "doctor": frozenset(),
    "land": frozenset({"asks", "checks", "slots"}),
    "look": frozenset({"artifacts", "asks", "checks"}),
    "loop": frozenset({"asks", "release", "report", "run", "slots"}),
    "pipeline": frozenset(),
    "plan": frozenset({"asks", "checks"}),
    "prune": frozenset({"reconcile", "release", "run", "track"}),
    "reconcile": frozenset({"release"}),
    "release": frozenset({"checks"}),
    "report": frozenset({"asks", "reconcile"}),
    "review": frozenset({"asks", "checks"}),
    "slots": frozenset(),
    "track": frozenset(),
    "write": frozenset({"artifacts", "asks", "checks"}),
}
COMPOSITION_ROOTS: Final = frozenset({"launch", "run", "wire"})


def slice_problems(graph):
    out = []
    known = SLICE_IMPORTS.keys() | COMPOSITION_ROOTS
    for module, targets in graph.items():
        parts = module.split(".")
        if parts[:2] != ["taskloop", "app"] or len(parts) < 3:
            continue
        source = parts[2]
        if source not in known:
            out.append(f"{module}: new slice needs an explicit import policy")
            continue
        for target in targets:
            bits = target.split(".")
            if bits[:2] != ["taskloop", "app"] or len(bits) < 3 or bits[2] == source:
                continue
            if source not in COMPOSITION_ROOTS and bits[2] not in SLICE_IMPORTS[source]:
                out.append(f"{module}: {source} cannot import {target}")
    return out


WORLD_MODULES: Final = frozenset({"subprocess", "socket", "http", "urllib", "multiprocessing", "sqlite3", "requests"})
WORLD_CALLS: Final = frozenset({
    "open", "builtins.open", "time.time", "time.monotonic", "time.perf_counter", "time.sleep",
    "datetime.datetime.now", "datetime.datetime.today", "datetime.date.today",
})
FILE_EFFECTS: Final = frozenset({"read_text", "read_bytes", "write_text", "write_bytes", "unlink", "mkdir", "rmdir", "touch", "open"})


def domain_world_problems(module, tree):
    names = bindings(module, tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = qualified(node.func, names)
        root = name.split(".")[0]
        world = (root in WORLD_MODULES or name in WORLD_CALLS
                 or (root == "os" and not name.startswith("os.path."))
                 or (isinstance(node.func, ast.Attribute) and node.func.attr in FILE_EFFECTS))
        if world:
            out.append(f"{module}:{node.lineno}: domain touches world through {name}")
    return out
