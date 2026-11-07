"""TESTISO checks the real workspace and rejects an undeclared sibling even in lazy or type-only imports."""
import pytest

from rules.package_tests import problems


def member(root, folder, name, import_root, dependencies=(), dev=()):
    path = root / "packages" / folder
    path.mkdir(parents=True)
    (path / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\ndependencies = {list(dependencies)!r}\n'
        f'[dependency-groups]\ndev = {list(dev)!r}\n'
        f'[tool.hatch.build.targets.wheel]\npackages = ["src/{import_root}"]\n', encoding="utf-8",
    )
    return path


def test_workspace_tests_import_only_declared_dependencies():
    assert not (bad := problems()), "\n".join(bad)


@pytest.mark.parametrize("source,line", [
    ("import sibling.detail\n", 1),
    ("def lazy():\n    from sibling import detail\n", 2),
    ("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import sibling as other\n", 3),
])
@pytest.mark.parametrize("group", ["dependencies", "dev"])
def test_an_undeclared_sibling_fails_and_a_declared_sibling_passes(tmp_path, source, line, group):
    member(tmp_path, "other", "Other-Member", "sibling")
    owner = member(tmp_path, "owner", "owner", "own")
    tests = owner / "tests" / "nested"
    tests.mkdir(parents=True)
    (tests / "test_import.py").write_text(source, encoding="utf-8")
    assert problems(tmp_path) == [
        f"packages/owner/tests/nested/test_import.py:{line} imports sibling (undeclared in packages/owner/pyproject.toml)",
    ]
    manifest = owner / "pyproject.toml"
    manifest.write_text(manifest.read_text().replace(f"{group} = []", f'{group} = ["OTHER_member>=1"]'), encoding="utf-8")
    assert problems(tmp_path) == []


def test_standard_library_own_pytest_and_normalized_third_party_imports_pass(tmp_path):
    owner = member(tmp_path, "owner", "owner", "own", ["Some-Library[extra]>=1"], ["Dev-Library; python_version > '3'"])
    tests = owner / "tests"
    tests.mkdir()
    (tests / "test_import.py").write_text(
        "import os.path, own.api, pytest, some_library\nfrom dev_library import helper\n", encoding="utf-8",
    )
    assert problems(tmp_path) == []
