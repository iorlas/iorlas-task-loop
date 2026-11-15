"""Affected-test selection uses syntax and structured shelf observations only."""

import ast
import importlib.util
import sys
from pathlib import Path

import pytest
from git_porcelain import GitUnavailable, Recorded
from git_porcelain.testing import FakeRemote, FakeRepo, FakeWorktree

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("affected", ROOT / "tools/affected.py")
assert SPEC is not None and SPEC.loader is not None
affected = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = affected
SPEC.loader.exec_module(affected)
POLICY_SPEC = importlib.util.spec_from_file_location("affected_policy", ROOT / "tests/rules/test_policy.py")
assert POLICY_SPEC is not None and POLICY_SPEC.loader is not None
policy = importlib.util.module_from_spec(POLICY_SPEC)
POLICY_SPEC.loader.exec_module(policy)


def project(root: Path, files: dict[str, str]) -> Path:
    files = {
        "pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests/unit", "tests/other"]\npythonpath = ["tests/helpers"]\n',
        "src/pkg/__init__.py": "",
        "src/pkg/leaf.py": "VALUE = 1\n",
        "src/pkg/middle.py": "from . import leaf as renamed\n",
        "tests/helpers/shared.py": "import pkg.middle as middle\n",
        "tests/unit/test_direct.py": "from pkg.leaf import VALUE\n",
        "tests/unit/test_transitive.py": "from shared import middle\n",
        "tests/other/test_unrelated.py": "import pathlib\n",
        **files,
    }
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return root


def selected(root: Path, *changes: str) -> list[str]:
    return [str(path.relative_to(root)) for path in affected.select_tests(root, frozenset(changes))]


def test_direct_transitive_helpers_aliases_and_cycles(tmp_path: Path) -> None:
    root = project(tmp_path, {"src/pkg/leaf.py": "from . import middle\nVALUE = 1\n"})
    assert selected(root, "src/pkg/leaf.py") == ["tests/unit/test_direct.py", "tests/unit/test_transitive.py"]
    assert selected(root, "tests/helpers/shared.py") == ["tests/unit/test_transitive.py"]
    assert selected(root, "src/pkg/__init__.py") == ["tests/unit/test_direct.py", "tests/unit/test_transitive.py"]


def test_relative_parents_and_package_from_imports(tmp_path: Path) -> None:
    root = project(tmp_path, {
        "src/pkg/nested/__init__.py": "from ..middle import renamed\n",
        "tests/unit/test_transitive.py": "from pkg import nested as alias\n",
    })
    assert selected(root, "src/pkg/leaf.py") == ["tests/unit/test_direct.py", "tests/unit/test_transitive.py"]


def test_namespace_package_imports(tmp_path: Path) -> None:
    root = project(tmp_path, {})
    (root / "src/pkg/__init__.py").unlink()
    assert selected(root, "src/pkg/leaf.py") == ["tests/unit/test_direct.py", "tests/unit/test_transitive.py"]


def test_changed_tests_and_conftest_descendants(tmp_path: Path) -> None:
    root = project(tmp_path, {
        "tests/unit/conftest.py": "from pkg.leaf import VALUE\n",
        "tests/unit/nested/test_child.py": "",
    })
    descendants = ["tests/unit/nested/test_child.py", "tests/unit/test_direct.py", "tests/unit/test_transitive.py"]
    assert selected(root, "tests/unit/test_direct.py") == ["tests/unit/test_direct.py"]
    assert selected(root, "tests/unit/conftest.py") == descendants
    assert selected(root, "src/pkg/leaf.py") == descendants
    (root / "tests/conftest.py").write_text("")
    assert len(selected(root, "tests/conftest.py")) == 4


def test_deleted_and_renamed_modules_retain_old_consumers(tmp_path: Path) -> None:
    root = project(tmp_path, {"src/pkg/new.py": "VALUE = 2\n"})
    (root / "src/pkg/leaf.py").unlink()
    assert selected(root, "src/pkg/leaf.py", "src/pkg/new.py") == [
        "tests/unit/test_direct.py", "tests/unit/test_transitive.py",
    ]


@pytest.mark.parametrize("change", ["pyproject.toml", "uv.lock", "justfile", "src/pkg/data.json", "tools/affected.py", "unknown.py"])
def test_unknown_or_resource_and_configuration_changes_widen(tmp_path: Path, change: str) -> None:
    root = project(tmp_path, {})
    assert len(selected(root, change)) == 3


@pytest.mark.parametrize("source", [
    "import pkg.missing\n", "import absent_dependency\n", "from .missing import value\n", "this is invalid Python!\n",
    "import importlib\nimportlib.import_module(name)\n", "__import__(name)\n",
    "from importlib import import_module as load\nload(name)\n",
    "from builtins import __import__ as load\nload(name)\n",
    'import importlib.util\nimportlib.util.spec_from_file_location("plugin", plugin_path)\n',
])
def test_unresolved_dependencies_and_syntax_widen(tmp_path: Path, source: str) -> None:
    root = project(tmp_path, {"src/pkg/middle.py": source})
    assert len(selected(root, "src/pkg/leaf.py")) == 3


@pytest.mark.parametrize("source", [
    'import importlib as loader\nloader.import_module("pkg.middle")\n',
    'from importlib import import_module as load\nload("pkg.middle")\n',
    '__import__("pkg.middle")\n',
])
def test_literal_dynamic_imports_are_edges(tmp_path: Path, source: str) -> None:
    root = project(tmp_path, {"tests/unit/test_transitive.py": source})
    assert selected(root, "src/pkg/leaf.py") == ["tests/unit/test_direct.py", "tests/unit/test_transitive.py"]


def test_documentation_and_clean_selection_do_not_parse_modules(tmp_path: Path) -> None:
    root = project(tmp_path, {"src/pkg/middle.py": "broken syntax!"})
    assert selected(root) == []
    assert selected(root, "docs/guide.md", "README.md") == []


def test_graph_never_executes_project_modules(tmp_path: Path) -> None:
    root = project(tmp_path, {"src/pkg/leaf.py": 'raise RuntimeError("must not be imported")\n'})
    assert selected(root, "src/pkg/leaf.py") == ["tests/unit/test_direct.py", "tests/unit/test_transitive.py"]


def test_changed_paths_combines_commits_index_working_tree_and_untracked(tmp_path: Path) -> None:
    remote = FakeRemote("https://example.invalid/repo.git")
    base = remote.advance("main", {"committed.py": "old", "staged.py": "old", "unstaged.py": "old", "old.py": "old"})
    repo = FakeRepo.clone(remote, tmp_path)
    worktree = repo.worktree(tmp_path)
    worktree.write_file("committed.py", "new")
    worktree.remove_file("old.py")
    worktree.write_file("renamed.py", "old")
    assert isinstance(worktree.record("change", paths="all"), Recorded)
    worktree.write_file("staged.py", "new")
    worktree.stage(("staged.py",))
    worktree.write_file("unstaged.py", "new")
    worktree.write_file("untracked.py", "new")
    assert affected.changed_paths(worktree, base) == frozenset({
        "committed.py", "old.py", "renamed.py", "staged.py", "unstaged.py", "untracked.py",
    })
    assert affected.changed_paths(worktree) == frozenset({"staged.py", "unstaged.py", "untracked.py"})


def test_read_failures_propagate(tmp_path: Path) -> None:
    worktree = FakeRepo.init(tmp_path).worktree(tmp_path)
    with pytest.raises(GitUnavailable):
        affected.changed_paths(worktree, "missing-ref")


@pytest.mark.parametrize(("changes", "status"), [(frozenset(), 0), (frozenset({"src/pkg/leaf.py"}), 5)])
def test_main_executes_selection_once_and_propagates_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: frozenset[str], status: int,
) -> None:
    root = project(tmp_path, {})
    repo = FakeRepo.init(root)
    observed: list[tuple[Path, bool, int]] = []
    calls: list[list[str]] = []
    bases: list[str] = []

    def open_repo(path: Path, *, memoize: bool, read_timeout: int) -> FakeRepo:
        observed.append((path, memoize, read_timeout))
        return repo

    def read_changes(worktree: FakeWorktree, base: str) -> frozenset[str]:
        assert worktree.path == root
        bases.append(base)
        return changes

    def run(paths: list[str]) -> int:
        calls.append(paths)
        return status

    monkeypatch.setattr(affected, "__file__", str(root / "tools/affected.py"))
    monkeypatch.setattr(affected, "RealRepo", open_repo)
    monkeypatch.setattr(affected, "changed_paths", read_changes)
    monkeypatch.setattr(affected.pytest, "main", run)
    assert affected.main(["--base", "origin/main"]) == status
    assert observed == [(root, False, 30)]
    assert bases == ["origin/main"]
    expected = [[str(root / path) for path in ["tests/unit/test_direct.py", "tests/unit/test_transitive.py"]]] if changes else []
    assert calls == expected


def test_main_reports_git_failure_without_running_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    monkeypatch.setattr(affected, "__file__", str(tmp_path / "tools/affected.py"))
    monkeypatch.setattr(affected, "RealRepo", lambda *args, **kwargs: FakeRepo.init(tmp_path))
    assert affected.main([]) == 1
    assert "Cannot select affected tests:" in capsys.readouterr().err


def test_selector_has_no_process_escape_hatch() -> None:
    tree = ast.parse((ROOT / "tools/affected.py").read_text())
    assert policy.process_replacements(tree) == []
    imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not {"subprocess", "os", "signal"} & set(imports)


def test_fast_recipe_invokes_isolated_selector_after_install() -> None:
    recipe = (ROOT / "justfile").read_text().split("test-fast *args: install\n", 1)[1].splitlines()[0]
    assert recipe.strip() == "uv run --frozen --no-sync python -I tools/affected.py {{args}}"
