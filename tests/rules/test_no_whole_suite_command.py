"""No code the factory runs builds a pytest command: the tests that run come from the profile's command (`just test`, which selects
what the change can break, dev/affected.py). Only `just test-full`, a person's recipe in the justfile, runs the whole tests tree."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TREES = ("src/taskloop", "skills/task-loop")
PYTEST = re.compile(r"(?:^|[\s/])pytest(?:\s|$)|-m\s+pytest|\"pytest\"")


def docstrings(tree):
    return {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}


def pytest_commands(source):
    """The string constants (docstrings left out) that name pytest as a program or a list element, with their line numbers."""
    tree = ast.parse(source)
    skip = docstrings(tree)
    found = [(n.lineno, n.value) for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip and PYTEST.search(n.value)]
    found += [(n.lineno, "pytest") for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and n.value == "pytest" and id(n) not in skip]
    return sorted(set(found))


def test_no_src_or_skill_code_builds_a_pytest_command():
    found = []
    for tree in TREES:
        for path in sorted((ROOT / tree).rglob("*.py")):
            if "_vendor" in path.parts:
                continue
            found += [f"{path.relative_to(ROOT)}:{line}: {text!r}" for line, text in pytest_commands(path.read_text(encoding="utf-8"))]
    assert found == [], "the factory runs the profile's command (`just test`), never pytest; the whole tree is `just test-full`, a person's"


def test_the_scan_sees_a_command_and_ignores_a_docstring():
    assert pytest_commands('argv = ["uv", "run", "pytest", "tests"]')
    assert pytest_commands('cmd = "uv run pytest tests -q"')
    assert pytest_commands('def f():\n    """The text pytest prints."""\n') == []
    assert pytest_commands('cmd = ["just", "test"]') == []
