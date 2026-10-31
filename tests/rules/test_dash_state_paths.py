"""LOCATOR (tl-9un.42): the dashboard reads state only through the run locator and ConfigDir. Under src/taskloop_dash no module names a
state file or folder of ours (every name ConfigDir joins to the config root), builds a path from another by `.parent.parent`, or builds a
ConfigDir outside the two places that take the config root (env.py, bind.py)."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
DASH = ROOT / "src" / "taskloop_dash"
PATHS = ROOT / "src" / "taskloop" / "contracts" / "paths.py"
MAKES_CONFIGDIR = {"env.py", "bind.py"}  # where the config root is taken from the process: everything else is handed a ConfigDir


def state_names() -> set[str]:
    """Every literal ConfigDir joins to the config root ("engine", "runs", "dash.pid", "repos.json", ...): the names of our state."""
    tree = ast.parse(PATHS.read_text(encoding="utf-8"))
    cfg = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "ConfigDir")
    names: set[str] = set()
    for n in ast.walk(cfg):
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
        tree = ast.parse(f.read_text(encoding="utf-8"))
        rel = f.relative_to(ROOT)
        out += [f"{rel}:{line}: names the state path {text!r}: go through ConfigDir or the run locator"
                for line, text in path_operands(tree) if text in names]
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr == "parent" and isinstance(n.value, ast.Attribute) and n.value.attr == "parent":
                out.append(f"{rel}:{n.lineno}: a path built from another by `.parent.parent`: ask the locator or ConfigDir")
            if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("ConfigDir") and f.name not in MAKES_CONFIGDIR:
                out.append(f"{rel}:{n.lineno}: a ConfigDir built here: take the one in Env")
    return out


class DashReadsThroughTheLocator(unittest.TestCase):
    def test_the_state_names_are_the_ones_configdir_joins(self):
        names = state_names()
        self.assertTrue({"engine", "runs", "dash.pid", "repos.json", "dash.token"} <= names, names)

    def test_no_dashboard_module_hardcodes_a_state_path(self):
        self.assertEqual(problems(), [])

    def test_the_rule_sees_a_hardcoded_path(self):
        bad = ast.parse('x = cfg.root / "engine" / "a.jsonl"\ny = os.path.join(root, "runs")\nz = p.parent.parent\nConfigDir(r)\n')
        self.assertEqual(sorted(t for _, t in path_operands(bad)), ["a.jsonl", "engine", "runs"])


if __name__ == "__main__":
    unittest.main()
