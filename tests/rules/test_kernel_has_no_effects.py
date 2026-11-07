"""The kernel contains records and pure rules, with one pending extraction."""
import ast

from rules.gate_rules import ROOT, parsed, py_files

KERNEL = "packages/kernel/src/tlkernel"
EXPECTED = {"check_files.py": "moves with #556 / tl-e5t0.16"}


def effects(tree: ast.Module) -> list[int]:
    """Find builtin open, os.replace (including aliases), and process/lock imports."""
    modules = {"os"}
    functions = set()
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.asname or alias.name for alias in node.names if alias.name == "os")
            if any(alias.name.split(".")[0] in {"subprocess", "fcntl"} for alias in node.names):
                found.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in {"subprocess", "fcntl"}:
                found.append(node.lineno)
            if node.module == "os":
                functions.update(alias.asname or alias.name for alias in node.names if alias.name == "replace")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if (isinstance(fn, ast.Name) and fn.id in {"open", *functions}) or (
                isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                and fn.value.id in modules and fn.attr == "replace"
            ):
                found.append(node.lineno)
    return sorted(found)


def test_kernel_has_no_effects():
    offenders = {
        path.relative_to(ROOT / KERNEL).as_posix(): EXPECTED.get(path.name, "must move to adapters")
        for path in py_files(ROOT, scan=(KERNEL,)) if effects(parsed(path)[1])
    }
    assert offenders == EXPECTED


def test_effects_detects_calls_and_imports():
    assert effects(ast.parse("open('x')\nimport os as host\nhost.replace('a', 'b')\n")) == [1, 3]
    assert effects(ast.parse("from os import replace as publish\npublish('a', 'b')\n")) == [2]
    assert effects(ast.parse("import subprocess as sp\nfrom fcntl import flock\n")) == [1, 2]
    assert effects(ast.parse("obj.open()\nobj.replace()\ntext = 'open()'\n")) == []
