"""Status queries and registration SQL belong to attempt_store."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "src" / "taskloop"


@pytest.mark.parametrize("module", ["attempt_reads.py", "composition.py", "launch.py"])
def test_status_and_registration_callers_have_no_sql(module: str) -> None:
    tree = ast.parse((ROOT / module).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"execute", "executemany", "executescript", "cursor"}, (module, node.lineno)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.lstrip().upper().startswith(
                ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "PRAGMA ")
            ), (module, node.lineno)
