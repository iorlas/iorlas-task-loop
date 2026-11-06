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

LAYERS = {
    "bead_env": 0, "briefing": 0, "briefs": 0, "cases": 0, "checkout": 0, "delegation": 0, "records": 0, "reload": 0,
    "requests": 0, "restart": 0, "stage_checks": 0, "stuck": 0, "waits": 0,
    "ask_flow": 1, "newfiles": 1, "pictures": 1, "rebase": 1, "reflector": 1, "routing": 1, "shared": 1, "shell": 1, "stage_loop": 1,
    "tree": 1,
    "fixer": 2, "hand": 2, "judge": 2, "link_check": 2, "owner_look": 2, "planner": 2,
    "resume": 3, "salvage": 3, "settles": 3, "worker": 3,
    "closer": 4, "lander": 4, "verifier": 4,
}


def imports(tree: ast.Module) -> dict[str, Path]:
    """{imported name: the file of its module} for the `taskloop.app` imports of one file."""
    found = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("taskloop.app."):
            path = APP / (n.module.removeprefix("taskloop.app.").replace(".", "/") + ".py")
            found.update({a.asname or a.name: path for a in n.names if path.is_file()})
    return found


def part_defs() -> dict[str, tuple[str, set[str], Path]]:
    """{part: (the class or factory that builds it, parts its property body names, the file of that class)}."""
    out = {}
    for name in PARTS_FILES:
        _, tree = parsed(APP / "run" / name)
        known = imports(tree)
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for item in cls.body:
                if isinstance(item, ast.Assign) and isinstance(item.value, ast.Call) \
                        and getattr(item.value.func, "id", "") == "cached_property":
                    arg = item.value.args[0]
                    target = item.targets[0]
                    assert isinstance(arg, ast.Name) and isinstance(target, ast.Name)
                    out[target.id] = (arg.id, set(), known[arg.id])
                elif isinstance(item, ast.FunctionDef) and any(getattr(d, "id", "") == "cached_property" for d in item.decorator_list):
                    built = next(c.func.id for c in ast.walk(item)
                                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in known)
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
