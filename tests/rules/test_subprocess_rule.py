"""Only process adapters and plain-python hooks may call raw subprocess entry points."""
import ast
from pathlib import Path

from tltestkit.case import Case

SRC = Path(__file__).resolve().parents[2] / "src"
HOME = {"taskloop/adapters/spawner.py", "taskloop/adapters/procs.py"}
BANNED = {"run", "Popen", "check_output", "call"}


def subprocess_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """The module aliases and entry points imported from subprocess."""
    modules = {"subprocess"}
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name == "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            functions.update(alias.asname or alias.name for alias in node.names if alias.name in BANNED)
            if any(alias.name == "*" for alias in node.names):
                functions.update(BANNED)
    return modules, functions


def raw_calls(text: str) -> list[int]:
    """Find qualified calls and from-imports, including import aliases; annotations are not calls."""
    tree = ast.parse(text)
    modules, functions = subprocess_names(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        qualified = (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                     and fn.value.id in modules and fn.attr in BANNED)
        if qualified or (isinstance(fn, ast.Name) and fn.id in functions):
            found.append(node.lineno)
    return sorted(found)


class SubprocessRule(Case):
    def test_raw_process_calls_stay_at_the_process_boundary(self):
        violations = []
        for path in sorted(SRC.rglob("*.py")):
            rel = path.relative_to(SRC).as_posix()
            if rel in HOME or rel.startswith("taskloop/hook/"):
                continue
            violations.extend(f"{rel}:{line}" for line in raw_calls(path.read_text(encoding="utf-8")))
        assert violations == [], "Use the Spawner or adapters.procs; there are no migration exceptions"

    def test_each_entry_point_and_import_alias_is_detected(self):
        for name in sorted(BANNED):
            with self.subTest(name=name):
                assert raw_calls(f"import subprocess\nsubprocess.{name}([])") == [2]
                assert raw_calls(f"import subprocess as sp\nsp.{name}([])") == [2]
                assert raw_calls(f"from subprocess import {name} as launch\nlaunch([])") == [2]
                assert raw_calls(f"from subprocess import *\n{name}([])") == [2]

    def test_types_exceptions_and_adapter_calls_are_allowed(self):
        assert raw_calls("import subprocess\np: subprocess.Popen[bytes]\n"
                                   "raise subprocess.TimeoutExpired([], 1)\nprocs.run([])\nspawner.run([])") == []
