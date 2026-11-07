"""Application slice imports and domain effects expressed as AST invariants."""
import ast
from typing import Final

from importgraph import bindings, qualified

# The former per-slice deny contracts, expressed once as allowed direct imports.
SLICE_IMPORTS: Final = {
    "checks": frozenset(),
    "doctor": frozenset(),
    "land": frozenset({"checks"}),
    "look": frozenset({"checks"}),
    "loop": frozenset({"release", "report", "run"}),
    "parts": frozenset({"checks", "land"}),  # the one list of stage parts imports each stage that owns its tables (store.py)
    "plan": frozenset({"checks"}),
    # prune -> slots: D-PRUNE is the cross-part runner, so it reads slot_state_roots
    "prune": frozenset({"reconcile", "release", "run", "track"}),
    "reconcile": frozenset({"release"}),
    "release": frozenset({"checks"}),
    "report": frozenset({"reconcile"}),
    "review": frozenset({"checks"}),
    "track": frozenset(),
    "workers": frozenset({"checks"}),
    "write": frozenset({"checks"}),
}
COMPOSITION_ROOTS: Final = frozenset({"launch", "run", "wire"})


def app_module(module):
    for stage, domain in (("review", {"findings", "availability"}), ("plan", {"matchers", "stored"}),
                          ("look", {"matchers", "shotspec"}), ("write", {"matchers"})):
        if module.startswith(f"tlwork.{stage}.") and module.rsplit(".", 1)[-1] not in domain:
            return module.replace(f"tlwork.{stage}", "taskloop.app." + stage, 1)
    return module


def slice_problems(graph):
    out = []
    known = SLICE_IMPORTS.keys() | COMPOSITION_ROOTS
    for original, targets in graph.items():
        module = app_module(original)
        parts = module.split(".")
        if parts[:2] != ["taskloop", "app"] or len(parts) < 3:
            continue
        source = parts[2]
        if source not in known:
            out.append(f"{module}: new slice needs an explicit import policy")
            continue
        for original_target in targets:
            target = original_target
            if target in {"tlwork", "tlwork.review", "tlwork.work", "tlwork.prompts", "tlwork.plan", "tlwork.look", "tlwork.write"}:
                continue
            target = app_module(target)
            bits = target.split(".")
            if target == "tlgate":
                continue  # package parent of both application and domain imports
            if bits[0] == "tlgate" and bits[1:2] != ["domain"]:
                bits = ["taskloop", "app", "checks", *bits[1:]]
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
