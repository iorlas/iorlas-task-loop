"""The layer-1 rules for src/taskloop/contracts, checked on the tree: stdlib and the vendored shelf packages only, no regex, no lazy imports, our file names only
in paths.py, 400 SLOC per file, 80 per function (SLOC: non-blank, non-comment, non-docstring lines)."""
import ast
import io
import sys
import tokenize
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401

PKG = Path(__file__).resolve().parents[2] / "src" / "taskloop" / "contracts"
FILES = sorted(PKG.glob("*.py"))
FILE_CAP, FUNC_CAP = 400, 80
VENDORED = {"atomic_io", "jsonl_log", "process_lock"}  # the shelf packages under skills/task-loop/_vendor that src may import
FORBIDDEN = {"re", "subprocess", "socket", "urllib", "http", "threading", "multiprocessing"}
OUR_NAMES = {"engine", "asks", "checkpoints", "runs", "loop", "slots", "locks", "snapshots", "sessions", "shared", "releases"}


def docstring_lines(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                out.update(range(body[0].lineno, body[0].end_lineno + 1))
    return out


def code_lines(src: str, tree: ast.AST) -> set[int]:
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    lines: set[int] = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type not in skip:
            lines.update(range(tok.start[0], tok.end[0] + 1))
    return lines - docstring_lines(tree)


class ContractRules(unittest.TestCase):
    def parsed(self):
        for f in FILES:
            src = f.read_text(encoding="utf-8")
            yield f, src, ast.parse(src)

    def test_the_package_is_there(self):
        self.assertGreater(len(FILES), 15)

    def test_caps(self):
        for f, src, tree in self.parsed():
            code = code_lines(src, tree)
            with self.subTest(f.name):
                self.assertLessEqual(len(code), FILE_CAP, "%s has %d SLOC" % (f.name, len(code)))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    n = len({i for i in code if node.lineno <= i <= node.end_lineno})
                    with self.subTest("%s:%s" % (f.name, node.name)):
                        self.assertLessEqual(n, FUNC_CAP, "%s.%s has %d SLOC" % (f.name, node.name, n))

    def test_imports_are_stdlib_or_this_package_and_never_inside_a_function(self):
        stdlib = set(sys.stdlib_module_names)
        for f, _, tree in self.parsed():
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for inner in ast.walk(node):
                        self.assertNotIsInstance(inner, (ast.Import, ast.ImportFrom), "%s: import inside %s" % (f.name, node.name))
            for node in ast.walk(tree):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                         [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else [])
                for name in names:
                    top = name.split(".")[0]
                    with self.subTest("%s imports %s" % (f.name, name)):
                        self.assertNotIn(top, FORBIDDEN)
                        self.assertTrue(top in stdlib or top in VENDORED or name.startswith("taskloop.contracts") or name == "taskloop.contracts", name)
                if isinstance(node, ast.ImportFrom):
                    self.assertEqual(node.level, 0, "%s: relative import" % f.name)

    def test_our_file_names_are_written_in_paths_py_only(self):
        for f, src, tree in self.parsed():
            if f.name == "paths.py":
                continue
            doc = docstring_lines(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.lineno not in doc:
                    v = node.value
                    with self.subTest("%s:%d" % (f.name, node.lineno)):
                        self.assertFalse(v.endswith((".json", ".jsonl", ".lock")) or v in OUR_NAMES or v.startswith(".task"), v)

    def test_every_module_has_a_docstring(self):
        for f, _, tree in self.parsed():
            if f.stat().st_size:
                self.assertTrue(ast.get_docstring(tree), f.name)


if __name__ == "__main__":
    unittest.main()
