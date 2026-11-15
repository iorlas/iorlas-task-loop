"""Orchestration contains no SQL execution; schema declarations remain declarative."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "src" / "taskloop"


@pytest.mark.parametrize(
    "module",
    [
        "attempt_reads.py", "attempt_loads.py", "attempt_entry.py", "composition.py",
        "launch.py", "publish.py", "slot_release.py", "slots.py",
        "check_admit.py", "factory_schema.py",
        *(str(path.relative_to(ROOT)) for path in sorted((ROOT / "recovery").glob("*.py"))
          if path.name not in {"store.py", "state_store.py"}),
    ],
)
def test_attempt_read_modules_and_registration_callers_have_no_sql(module: str) -> None:
    tree = ast.parse((ROOT / module).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            application_execute = (
                node.func.attr == "execute" and (module, ast.unparse(node.func.value)) in {
                    ("attempt_entry.py", "app"),
                    ("recovery/continue_attempt.py", "store"),
                    ("recovery/continue_attempt.py", "self.attempts"),
                    ("recovery/complete_attempt.py", "self.attempts"),
                }
            )
            assert application_execute or node.func.attr not in {"execute", "executemany", "executescript", "cursor"}, (
                module, node.lineno
            )
        if module != "factory_schema.py" and isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not node.value.lstrip().upper().startswith(
                ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "PRAGMA ")
            ), (module, node.lineno)
