"""SQLite exceptions grant exact import permissions without exempting other banned APIs."""

import ast
import importlib.util
import tomllib
from configparser import ConfigParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sqlite_contract_generator", ROOT / "tools/generate_import_contracts.py")
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)
SECTION = "importlinter:contract:sqlite-only-in-stores"


def configuration(text: str) -> ConfigParser:
    config = ConfigParser(interpolation=None)
    config.read_string(text)
    return config


def imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def assert_no_banned_imports(source: str, banned: set[str]) -> None:
    for name in imports(source):
        assert not any(name == api or name.startswith(api + ".") for api in banned), name


def test_sqlite_contract_covers_every_non_store_including_initializers() -> None:
    config = configuration((ROOT / ".importlinter").read_text())
    contract = config[SECTION]
    files = generator.modules(ROOT)
    assert set(contract["source_modules"].split()) == {module for module, path in files.items() if path.name != "store.py"}
    covered = set(contract["source_modules"].split()) | {module for module, path in files.items() if path.name == "store.py"}
    # Independently walk the tree so omitted modules in the generator cannot hide missing coverage.
    for path in (ROOT / "src/taskloop").rglob("*.py"):
        relative = path.relative_to(ROOT / "src")
        module = relative.parent.as_posix() if path.name == "__init__.py" else relative.with_suffix("").as_posix()
        assert module.replace("/", ".") in covered, relative
    assert contract["forbidden_modules"].strip() == "sqlite3"
    assert contract["type"] == "forbidden"
    assert contract["as_packages"] == "False"
    assert contract["allow_indirect_imports"] == "True"
    assert contract["unmatched_ignore_alerting"] == "error"
    assert config["importlinter"]["exclude_type_checking_imports"] == "False"
    assert config["importlinter"]["include_external_packages"] == "True"


def assert_permissions(config: ConfigParser, permissions: dict[str, list[str]]) -> None:
    files = generator.modules(ROOT)
    owners = {module for module, path in files.items() if path.name == "store.py"}
    exceptions = set()
    for line in config[SECTION].get("ignore_imports", "").splitlines():
        if not line.strip():
            continue
        importer, separator, imported = line.strip().partition(" -> ")
        assert separator and imported == "sqlite3" and importer in files
        assert "sqlite3" in imports(files[importer].read_text()), "Remove stale SQLite exceptions"
        exceptions.add(importer)
    expected = {str(files[module].relative_to(ROOT)) for module in owners | exceptions}
    assert permissions == {"tests/**": ["TID251"], **{path: ["TID251"] for path in sorted(expected)}}


def test_ruff_permissions_match_only_literal_stores_and_exact_exceptions() -> None:
    config = configuration((ROOT / ".importlinter").read_text())
    lint = tomllib.loads((ROOT / "ruff.toml").read_text())["lint"]
    assert {"sqlite3", "subprocess"} <= lint["flake8-tidy-imports"]["banned-api"].keys()
    assert "TID251" in lint["select"] and "TID251" not in lint["ignore"]
    assert_permissions(config, lint["per-file-ignores"])


def test_ruff_sqlite_permissions_never_exempt_other_banned_apis() -> None:
    lint = tomllib.loads((ROOT / "ruff.toml").read_text())["lint"]
    banned = set(lint["flake8-tidy-imports"]["banned-api"]) - {"sqlite3"}
    paths = set((ROOT / "tests").rglob("*.py"))
    paths.update(ROOT / path for path in lint["per-file-ignores"] if path != "tests/**")
    for path in sorted(paths):
        assert_no_banned_imports(path.read_text(), banned)


@pytest.mark.parametrize("source", [
    "import sqlite3 as db", "from sqlite3 import Connection as Con",
    "if TYPE_CHECKING:\n    from sqlite3 import Connection", "import sqlite3.dbapi2 as db",
])
def test_sqlite_aliases_and_type_only_imports_are_visible(source: str) -> None:
    with pytest.raises(AssertionError, match="sqlite3"):
        assert_no_banned_imports(source, {"sqlite3"})


@pytest.mark.parametrize("source", ["import subprocess as proc", "from subprocess import run as execute"])
def test_sqlite_permission_cannot_hide_another_banned_import(source: str) -> None:
    with pytest.raises(AssertionError, match="subprocess"):
        assert_no_banned_imports(source, {"subprocess"})


@pytest.mark.parametrize("extra", ["src/taskloop/*.py", "src/taskloop/profile.py"])
def test_wildcard_and_spare_ruff_permissions_fail(extra: str) -> None:
    config = configuration((ROOT / ".importlinter").read_text())
    lint = tomllib.loads((ROOT / "ruff.toml").read_text())["lint"]
    permissions = dict(lint["per-file-ignores"])
    permissions[extra] = ["TID251"]
    with pytest.raises(AssertionError):
        assert_permissions(config, permissions)


def test_indirect_store_callers_are_covered_without_a_sqlite_exception(tmp_path: Path) -> None:
    folder = tmp_path / "src/taskloop/feature"
    folder.mkdir(parents=True)
    (folder / "store.py").write_text("import sqlite3\n")
    (folder / "api.py").write_text("from . import store\n")
    (folder / "other_store.py").write_text("")
    config = configuration(generator.generate(tmp_path, "[importlinter]\nroot_package = taskloop\n"))
    assert set(config[SECTION]["source_modules"].split()) == {"taskloop.feature.api", "taskloop.feature.other_store"}
    assert "ignore_imports" not in config[SECTION]
