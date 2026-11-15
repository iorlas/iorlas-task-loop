"""Attempt reads, entry, registration callers and slot orchestration contain no SQL."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "src" / "taskloop"


@pytest.mark.parametrize(
    "module",
    ["attempt_reads.py", "attempt_loads.py", "attempt_entry.py", "composition.py", "launch.py", "slot_release.py", "slots.py"],
)
def test_attempt_read_modules_and_registration_callers_have_no_sql(module: str) -> None:
    tree = ast.parse((ROOT / module).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            application_execute = (
                module == "attempt_entry.py" and node.func.attr == "execute"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "app"
            )
            assert application_execute or node.func.attr not in {"execute", "executemany", "executescript", "cursor"}, (
                module, node.lineno
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.lstrip().upper().startswith(
                ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "PRAGMA ")
            ), (module, node.lineno)
