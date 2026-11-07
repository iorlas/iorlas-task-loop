"""Dashboard package tests cannot import the task-loop shell, including inside functions."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def shell_imports(root: Path) -> list[str]:
    found = []
    for path in sorted((root / "tests" / "dash").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if name == "taskloop" or name.startswith("taskloop."):
                    found.append(f"{path.relative_to(root)}:{node.lineno}: {name}")
    return found


def test_dashboard_tests_import_no_shell_modules():
    assert shell_imports(ROOT) == []


@pytest.mark.parametrize("statement", ["import taskloop", "import taskloop.app.run as run", "from taskloop import app",
                                       "from taskloop.app.run import layout"])
def test_rule_finds_lazy_shell_imports(tmp_path: Path, statement: str):
    folder = tmp_path / "tests" / "dash" / "real"
    folder.mkdir(parents=True)
    (folder / "test_mutation.py").write_text(f"def lazy():\n    {statement}\n", encoding="utf-8")
    assert shell_imports(tmp_path) == [f"tests/dash/real/test_mutation.py:2: {statement.split()[1]}"]


def test_rule_allows_dashboard_kernel_and_relative_imports(tmp_path: Path):
    folder = tmp_path / "tests" / "dash"
    folder.mkdir(parents=True)
    (folder / "test_allowed.py").write_text(
        "import taskloop_dash\nfrom taskloop_dash.app import Dash\nimport tlkernel\nfrom .taskloop import fixture\n",
        encoding="utf-8",
    )
    assert shell_imports(tmp_path) == []
