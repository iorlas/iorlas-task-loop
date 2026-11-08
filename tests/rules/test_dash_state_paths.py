"""State names belong to core or stage path modules; dashboard readers use those helpers and the run locator."""
import ast
import sys
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "packages" / "dash" / "src" / "tldash"
PATHS = ROOT / "packages" / "kernel" / "src" / "tlkernel" / "paths.py"
PLAIN_PYTHON = {"prepush.py", "layout_migrate.py", "key_migrate.py"}  # no record in the hook (.importlinter); migrators name OLD places
STAGE_PATHS = {
    ROOT / "src" / name for name in (
        "taskloop/app/prune/paths.py",
        "taskloop/adapters/layout_paths.py",
    )
} | {
    ROOT / "packages/land/src/tlland/paths.py",
    ROOT / "packages/artifacts/src/tlartifacts/paths.py", ROOT / "packages/slots/src/tlslots/paths.py",
     ROOT / "packages/asks/src/tlasks/paths.py", ROOT / "packages/release/src/tlrelease/paths.py", DASH / "paths.py"}
MAKES_CONFIGDIR = {"env.py", "bind.py", "testing.py"}  # where the config root is made: everything else is handed a ConfigDir


def state_names() -> set[str]:
    """Every literal the core or stage path helpers join to the config root."""
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in sorted(STAGE_PATHS | {PATHS})]
    names: set[str] = set()
    for n in (node for tree in trees for node in ast.walk(tree)):
        under_root = isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) and isinstance(n.left, ast.Attribute) and n.left.attr == "root"
        if under_root and isinstance(n.right, ast.Constant) and isinstance(n.right.value, str):  # type: ignore[union-attr]
            names.add(n.right.value)
    return names


def path_operands(tree: ast.AST) -> list[tuple[int, str]]:
    """(line, text) of every string used as a path part: right of `/`, or an argument of Path(...), os.path.join(...), .joinpath(...)."""
    found: list[tuple[int, str]] = []
    for n in ast.walk(tree):
        parts: list[ast.expr] = []
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            base = n.left
            while isinstance(base, ast.BinOp):
                base = base.left
            if "home" not in ast.unparse(base):  # ~/.claude/plugins/cache is the user's home, not our state
                parts = [n.right]
        elif isinstance(n, ast.Call):
            fn = ast.unparse(n.func)
            if fn in ("Path", "os.path.join", "pathlib.Path") or fn.endswith(".joinpath"):
                parts = list(n.args)
        for p in parts:
            if isinstance(p, ast.Constant) and isinstance(p.value, str):
                found.append((p.lineno, p.value))
    return found


def problems() -> list[str]:
    names = state_names()
    out: list[str] = []
    for f in sorted(DASH.rglob("*.py")):
        if f in STAGE_PATHS:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        rel = f.relative_to(ROOT)
        out += [f"{rel}:{line}: names the state path {text!r}: go through the owning path helper or the run locator"
                for line, text in path_operands(tree) if text in names]
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr == "parent" and isinstance(n.value, ast.Attribute) and n.value.attr == "parent":
                out.append(f"{rel}:{n.lineno}: a path built from another by `.parent.parent`: ask the locator or ConfigDir")
            if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("ConfigDir") and f.name not in MAKES_CONFIGDIR:
                out.append(f"{rel}:{n.lineno}: a ConfigDir built here: take the one in Env")
    return out


class DashReadsThroughTheLocator(Case):
    def test_the_state_names_are_the_ones_configdir_joins(self):
        names = state_names()
        assert {"repos", "runs", "dash.pid", "repos.json"} <= names, names

    def test_no_dashboard_module_hardcodes_a_state_path(self):
        assert problems() == []

    def test_the_rule_sees_a_hardcoded_path(self):
        bad = ast.parse('x = cfg.root / "engine" / "a.jsonl"\ny = os.path.join(root, "runs")\nz = p.parent.parent\nConfigDir(r)\n')
        assert sorted(t for _, t in path_operands(bad)) == ["a.jsonl", "engine", "runs"]


class PathsIsTheOnlyNamingPoint(Case):
    def test_no_taskloop_module_but_paths_names_a_state_folder_of_ours(self):
        names = state_names()
        found = [f"{f.relative_to(ROOT)}:{line}: names the state path {text!r}: use the owning stage path module"
                 for f in sorted((ROOT / "src" / "taskloop").rglob("*.py")) if f not in STAGE_PATHS and f.name not in PLAIN_PYTHON
                 for line, text in path_operands(ast.parse(f.read_text(encoding="utf-8"))) if text in names]
        assert found == []
