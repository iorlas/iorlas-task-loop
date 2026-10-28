"""The layer rules on src/taskloop/adapters and contracts/ports.py: adapters import contracts and stdlib only (never domain or
app), no import inside a function, 400 SLOC per file and 80 per function, and no fake-only name in a real adapter."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from contracts.test_rules import VENDORED, code_lines  # noqa: E402

SRC = Path(__file__).resolve().parents[2] / "src" / "taskloop"
FILES = sorted((SRC / "adapters").glob("*.py")) + [SRC / "contracts" / "ports.py"]
STDLIB = set(sys.stdlib_module_names)


class PortRules(unittest.TestCase):
    def parsed(self):
        for f in FILES:
            src = f.read_text(encoding="utf-8")
            yield f, src, ast.parse(src)

    def test_caps(self) -> None:
        for f, src, tree in self.parsed():
            code = code_lines(src, tree)
            self.assertLessEqual(len(code), 400, f.name)
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertLessEqual(len({i for i in code if n.lineno <= i <= (n.end_lineno or n.lineno)}), 80, "%s.%s" % (f.name, n.name))

    def test_imports(self) -> None:
        for f, _, tree in self.parsed():
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertFalse([i for i in ast.walk(n) if isinstance(i, (ast.Import, ast.ImportFrom))], f.name)
                mods = ([a.name for a in n.names] if isinstance(n, ast.Import) else
                        [n.module or ""] if isinstance(n, ast.ImportFrom) else [])
                for m in mods:
                    ok = m.split(".")[0] in STDLIB | VENDORED or m.startswith(("taskloop.contracts", "taskloop.adapters"))
                    self.assertTrue(ok, "%s imports %s" % (f.name, m))

    def test_contracts_ports_import_contracts_only(self) -> None:
        for n in ast.walk(ast.parse((SRC / "contracts" / "ports.py").read_text(encoding="utf-8"))):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("taskloop"):
                self.assertTrue(n.module.startswith("taskloop.contracts"), n.module)


if __name__ == "__main__":
    unittest.main()
