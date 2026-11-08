"""The Engine's parts have an acyclic build order (docs/design/engine-order.md, tl-e5t0.57): an AST scan of the parts files finds which
part each part reads off the host, and the layers that follow must equal LAYERS. A new part, or a new read of one, has to be placed
there; a cycle among parts, or a part reading a higher layer, fails."""
import ast
from pathlib import Path

from rules.gate_rules import parsed

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src/taskloop/app"
PARTS_FILES = ("parts_run.py", "parts_land.py", "parts_plan.py", "host.py", "engine.py")
# how a part holds the engine: `self.e`, `self.host`, `self.h`, a local alias, or the look stage's two views of it (`hand`, `ports`)
HOST_NAMES = {"e", "host", "h", "hand", "ports"}

# Resume and reflector take collaborators as role arguments.
# Construction layers include run composition roots (bead_env, shell, stage_checks) and package nodes (ask_flow, shared).
# This is a build-order table, independent of the node/root import classification.
LAYERS = {
    "bead_env": 0, "briefing": 0, "briefs": 0, "checkout": 0, "delegation": 0, "leftover_sink": 0, "records": 0, "reload": 0,
    "reflector": 0, "resume": 0, "requests": 0, "stage_checks": 0, "stuck": 0, "waits": 0,
    "ask_flow": 1, "cases": 1, "newfiles": 1, "pictures": 1, "routing": 1, "shared": 1, "shell": 1,
    "stage_loop": 1, "tree": 1,
    "fixer": 2, "hand": 2, "judge": 2, "link_check": 2, "owner_look": 2, "planner": 2, "rebase": 2,
    "restart": 3, "salvage": 3, "settles": 3, "worker": 3,
    "closer": 4, "lander": 4, "verifier": 4,
}


PACKAGE_SRC = {"tlpipeline": "packages/pipeline/src", "tlwork": "packages/work/src",
               "tlland": "packages/land/src",
               "tlslots": "packages/slots/src", "tlasks": "packages/asks/src", "tlrelease": "packages/release/src"}


def api_homes(package: str = "tlpipeline") -> dict[str, Path]:
    """{name: the defining module file a package's api.py re-exports it from}."""
    source = ROOT / PACKAGE_SRC[package]
    tree = ast.parse((source / package / "api.py").read_text(encoding="utf-8"))
    return {a.asname or a.name: source / (n.module.replace(".", "/") + ".py")
            for n in tree.body if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(package + ".")
            for a in n.names if (source / (n.module.replace(".", "/") + ".py")).is_file()}


def imports(tree: ast.Module) -> dict[str, Path]:
    """{imported name: the file of its module} for the app, pipeline, work and slots imports of one file."""
    found = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in {"tlpipeline.api", "tlwork.api"}:
            homes = api_homes(n.module.split(".")[0])
            found.update({a.asname or a.name: homes[a.name] for a in n.names if a.name in homes})
            continue
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(
                ("tlland.", "taskloop.app.", "tlpipeline.", "tlwork.", "tlslots.", "tlasks.", "tlrelease.")):
            package = n.module.split(".")[0]
            base, module = ((ROOT / PACKAGE_SRC[package], n.module) if package in PACKAGE_SRC
                            else (APP, n.module.removeprefix("taskloop.app.")))
            path = base / (module.replace(".", "/") + ".py")
            found.update({a.asname or a.name: path for a in n.names if path.is_file()})
    return found


def imports_of_module(tree: ast.Module) -> set[str]:
    """The names a file binds with `from tlpipeline import ...` (so `api` when it calls `api.X(...)`)."""
    return {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "tlpipeline" for a in n.names}


def callee(call: ast.Call, known: dict[str, Path]) -> str:
    """The name of the class or factory a call builds: `X(...)` or `api.X(...)` with X a known part class."""
    f = call.func
    if isinstance(f, ast.Name) and f.id in known:
        return f.id
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "api" and f.attr in known:
        return f.attr
    return ""


def part_defs() -> dict[str, tuple[str, set[str], Path]]:
    """{part: (the class or factory that builds it, parts its property body names, the file of that class)}."""
    out = {}
    for name in PARTS_FILES:
        _, tree = parsed(APP / "run" / name)
        known = imports(tree) | (api_homes() if "api" in imports_of_module(tree) else {})
        known |= {n.name: known[n.returns.id] for n in tree.body  # a factory bound in the file itself reads what the class it returns reads
                  if isinstance(n, ast.FunctionDef) and isinstance(n.returns, ast.Name)}
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for item in cls.body:
                if isinstance(item, ast.Assign) and isinstance(item.value, ast.Call) \
                        and getattr(item.value.func, "id", "") == "cached_property":
                    arg = item.value.args[0]
                    target = item.targets[0]
                    if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) and arg.value.id == "api":
                        arg = ast.Name(id=arg.attr)  # `cached_property(api.X)` builds X as `cached_property(X)` does
                    assert isinstance(arg, ast.Name) and isinstance(target, ast.Name)
                    out[target.id] = (arg.id, set(), known[arg.id])
                elif isinstance(item, ast.FunctionDef) and any(getattr(d, "id", "") == "cached_property" for d in item.decorator_list):
                    built = next(callee(c, known) for c in ast.walk(item) if isinstance(c, ast.Call) and callee(c, known))
                    own = {a.attr for a in ast.walk(item) if isinstance(a, ast.Attribute) and getattr(a.value, "id", "") == "self"}
                    out[item.name] = (built, own, known[built])
    return out


def is_host(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id in HOST_NAMES) or (
        isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self" and node.attr in HOST_NAMES)


def reads(path: Path, parts: set[str]) -> set[str]:
    """The parts a module reads off the host, in a constructor, a factory or a method."""
    _, tree = parsed(path)
    return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in parts and is_host(n.value)}


def graph() -> dict[str, set[str]]:
    defs = part_defs()
    parts = set(defs)
    return {p: (reads(path, parts) | (own & parts)) - {p} for p, (_, own, path) in defs.items()}


def layers(edges: dict[str, set[str]]) -> dict[str, int]:
    """1 + the highest layer among the parts a part uses; a cycle is an error naming the parts in it."""
    done: dict[str, int] = {}

    def depth(p: str, trail: tuple[str, ...]) -> int:
        assert p not in trail, "parts form a cycle: " + " -> ".join((*trail[trail.index(p):], p))
        if p not in done:
            done[p] = 1 + max((depth(q, (*trail, p)) for q in edges[p]), default=-1)
        return done[p]

    return {p: depth(p, ()) for p in edges}


def test_the_parts_have_no_cycle_and_the_layers_are_the_documented_ones():
    assert layers(graph()) == LAYERS


def test_a_cycle_among_parts_is_named():
    try:
        layers({"a": {"b"}, "b": {"a"}})
    except AssertionError as e:
        assert "a -> b -> a" in str(e)
    else:
        raise AssertionError("a cycle went through")


def test_land_fields_has_one_caller():
    calls = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")
             if any(isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", "")) == "land_fields"
                    for n in ast.walk(parsed(p)[1]))]
    assert calls == ["src/taskloop/app/run/fields.py"]


def test_api_exports_resolve_to_the_defining_modules():
    for package, name, module in (("tlpipeline", "Closer", "closing"),
                                  ("tlwork", "Planner", "plan/planner")):
        tree = ast.parse(f"from {package}.api import {name} as part")
        home = imports(tree)["part"]
        assert home == ROOT / PACKAGE_SRC[package] / package / (module + ".py")
