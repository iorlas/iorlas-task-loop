"""Dashboard package tests cannot import the task-loop shell or the wiring tests, including inside functions."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_SUPPORT = frozenset({"dashes", "fakes", "look_world", "memstores", "spawn", "tlbd", "dlcall", "fake_beads"})


def shell_imports(root: Path) -> list[str]:
    found = []
    for path in sorted((root / "packages" / "dash" / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
                if node.module == "support":
                    names = [f"support.{alias.name}" for alias in node.names]
            for name in names:
                if (name in ("taskloop", "dashwire") or name.startswith(("taskloop.", "dashwire."))
                        or (name.startswith("support.") and name.split(".")[1] in ENGINE_SUPPORT)):
                    found.append(f"{path.relative_to(root)}:{node.lineno}: {name}")
    return found


def test_dashboard_tests_import_no_shell_modules():
    assert shell_imports(ROOT) == []


@pytest.mark.parametrize("statement", ["import taskloop", "import taskloop.app.run as run", "from taskloop import app",
                                       "from taskloop.app.run import engine", "from dashwire import test_dash_api"])
def test_rule_finds_lazy_shell_imports(tmp_path: Path, statement: str):
    folder = tmp_path / "packages" / "dash" / "tests" / "real"
    folder.mkdir(parents=True)
    (folder / "test_mutation.py").write_text(f"def lazy():\n    {statement}\n", encoding="utf-8")
    assert shell_imports(tmp_path) == [f"packages/dash/tests/real/test_mutation.py:2: {statement.split()[1]}"]


@pytest.mark.parametrize("module", sorted(ENGINE_SUPPORT))
@pytest.mark.parametrize("form", ["from support.{module} import fixture", "from support import {module}", "import support.{module}"])
def test_rule_finds_lazy_engine_support_imports(tmp_path: Path, module: str, form: str):
    folder = tmp_path / "packages" / "dash" / "tests"
    folder.mkdir(parents=True)
    statement = form.format(module=module)
    (folder / "test_mutation.py").write_text(f"def lazy():\n    {statement}\n", encoding="utf-8")
    assert shell_imports(tmp_path) == [f"packages/dash/tests/test_mutation.py:2: support.{module}"]


def test_rule_allows_dashboard_kernel_and_relative_imports(tmp_path: Path):
    folder = tmp_path / "packages" / "dash" / "tests"
    folder.mkdir(parents=True)
    (folder / "test_allowed.py").write_text(
        "import tldash\nfrom tldash.app import Dash\nimport tlkernel\nfrom .taskloop import fixture\n"
        "from tldash.testing import fixture\nfrom tldash import testing as factory_index\n"
        "import tldash.testing as dashlogs\nfrom .support.fakes import fixture\n",
        encoding="utf-8",
    )
    assert shell_imports(tmp_path) == []
