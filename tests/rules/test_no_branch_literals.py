"""Task branch prefixes belong to the kernel's branch naming module."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRANCHES = ROOT / "packages/kernel/src/tlkernel/branches.py"


def violations(source: str) -> list[int]:
    tree = ast.parse(source)
    prose = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("task/") and id(n) not in prose]


def test_no_branch_literals():
    found = []
    for top in [ROOT / "src", *sorted((ROOT / "packages").glob("*/src"))]:
        for path in sorted(top.rglob("*.py")):
            if path != BRANCHES:
                found += [f"{path.relative_to(ROOT)}:{line}" for line in violations(path.read_text(encoding="utf-8"))]
    assert found == []


def test_rule_sees_literals_and_allows_prose():
    assert violations('branch = "task/a"') == [1]
    assert violations('branch = f"task/{bead}"') == [1]
    assert violations('"task/prose"\ndef f():\n    "task/prose"\n') == []
    assert violations('branch = "other/task/a"') == []
