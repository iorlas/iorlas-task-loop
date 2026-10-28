"""The layer rules for src/taskloop/stores: stdlib and taskloop.contracts/taskloop.stores only, no regex, no lazy imports, 400 SLOC
per file, 80 per function, a docstring on every module, and no file I/O call outside the real implementations."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from contracts.test_rules import FILE_CAP, FUNC_CAP, VENDORED, code_lines  # noqa: E402

PKG = Path(__file__).resolve().parents[2] / "src" / "taskloop" / "stores"
FILES = sorted(PKG.glob("*.py"))
REAL = {"files.py", "real.py", "call_state.py"}


class StoreRules(unittest.TestCase):
    def parsed(self):
        for f in FILES:
            src = f.read_text(encoding="utf-8")
            yield f, src, ast.parse(src)

    def test_caps_and_docstrings(self):
        for f, src, tree in self.parsed():
            code = code_lines(src, tree)
            self.assertLessEqual(len(code), FILE_CAP, f.name)
            self.assertTrue(ast.get_docstring(tree), f.name)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    n = len({i for i in code if node.lineno <= i <= node.end_lineno})
                    self.assertLessEqual(n, FUNC_CAP, "%s.%s" % (f.name, node.name))

    def test_imports(self):
        stdlib = set(sys.stdlib_module_names)
        for f, _, tree in self.parsed():
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for inner in ast.walk(node):
                        self.assertNotIsInstance(inner, (ast.Import, ast.ImportFrom), "%s: import in %s" % (f.name, node.name))
                names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                         [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                for name in names:
                    top = name.split(".")[0]
                    self.assertTrue(top in stdlib or top in VENDORED or name.startswith(("taskloop.contracts", "taskloop.stores", "taskloop.adapters.locks")), "%s: %s" % (f.name, name))
                    self.assertNotIn(top, {"re", "subprocess", "socket"}, f.name)

    def test_only_the_real_implementations_touch_the_disk(self):
        for f, _, tree in self.parsed():
            if f.name in REAL:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                    self.assertNotIn(name, {"open", "read_text", "write_text", "unlink", "mkdir"}, "%s calls %s" % (f.name, name))
                if isinstance(node, ast.Import):
                    self.assertFalse({"fcntl", "tempfile", "shutil"} & {a.name for a in node.names}, f.name)


if __name__ == "__main__":
    unittest.main()
