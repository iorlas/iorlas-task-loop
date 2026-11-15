"""Folder changes must refresh native privacy contracts without granting exceptions."""

import ast
import importlib.util
from configparser import ConfigParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("generate_import_contracts", ROOT / "tools/generate_import_contracts.py")
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def configuration(text: str) -> ConfigParser:
    config = ConfigParser(interpolation=None)
    config.read_string(text)
    return config


def values(config: ConfigParser, section: str, key: str) -> set[str]:
    return set(config[section][key].split())


def project(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / "src/taskloop" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def assert_initializers_are_private(root: Path) -> None:
    files = generator.modules(root)
    for owner, owned in generator.slices(root, files).items():
        if owner not in owned:
            continue
        for node in ast.walk(ast.parse(files[owner].read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not node.level and not (node.module or "").startswith(owner), (owner, node.lineno)
            if isinstance(node, ast.Import):
                assert all(alias.name != owner and not alias.name.startswith(owner + ".") for alias in node.names), owner


def test_committed_contracts_match_folder_tree() -> None:
    text = (ROOT / ".importlinter").read_text()
    assert generator.generate(ROOT, text) == text, "Refresh the generated folder contracts"


def test_initializers_cannot_reexport_private_modules() -> None:
    assert_initializers_are_private(ROOT)


def test_new_nested_folders_protect_only_their_private_modules(tmp_path: Path) -> None:
    project(tmp_path, {
        "__init__.py": "", "flat.py": "", "feature/__init__.py": "", "feature/api.py": "",
        "feature/private.py": "", "feature/child/__init__.py": "", "feature/child/api.py": "",
        "feature/child/private.py": "", "feature/static/style.css": "", "static/app.js": "",
    })
    text = generator.generate(tmp_path, "[importlinter]\nroot_package = taskloop\n")
    config = configuration(text)
    parent = "importlinter:contract:slice-taskloop.feature"
    child = "importlinter:contract:slice-taskloop.feature.child"
    assert values(config, parent, "protected_modules") == {"taskloop.feature.private"}
    assert values(config, parent, "allowed_importers") == {
        "taskloop.feature", "taskloop.feature.api", "taskloop.feature.private",
    }
    assert values(config, child, "protected_modules") == {"taskloop.feature.child.private"}
    assert values(config, child, "allowed_importers") == {
        "taskloop.feature.child", "taskloop.feature.child.api", "taskloop.feature.child.private",
    }
    assert not any("static" in name or name.endswith("slice-taskloop") for name in config.sections())
    for name in (parent, child):
        assert config[name]["type"] == "protected"
        assert config[name]["as_packages"] == "False"
        assert config[name]["unmatched_ignore_imports_alerting"] == "error"
    assert generator.generate(tmp_path, text) == text
    project(tmp_path, {"feature/new.py": "", "other/private.py": ""})
    refreshed = generator.generate(tmp_path, text)
    assert refreshed != text
    assert "taskloop.feature.new" in refreshed
    assert "slice-taskloop.other" in refreshed


def test_generation_preserves_reviewed_exceptions_and_unrelated_text(tmp_path: Path) -> None:
    project(tmp_path, {"feature/private.py": "", "outsider.py": "from .feature import private"})
    before = "# Retained comment\n[importlinter]\nroot_package = taskloop\n\n[unrelated]\nvalue = retained\n\n"
    text = generator.generate(tmp_path, before)
    config = configuration(text)
    assert all("ignore_imports" not in config[section] for section in config.sections()), "Generation must not approve violations"
    text = text.replace(
        "unmatched_ignore_imports_alerting = error",
        "unmatched_ignore_imports_alerting = error\nignore_imports =\n    taskloop.outsider -> taskloop.feature.private",
    )
    assert generator.generate(tmp_path, text) == text
    assert text.startswith(before)


@pytest.mark.parametrize("added", [
    "shelf_request.py", "feature/__init__.py", "feature/new.py", "feature/api.py", "feature/child/private.py",
])
def test_new_module_invalidates_committed_coverage(tmp_path: Path, added: str) -> None:
    project(tmp_path, {"__init__.py": "", "feature/private.py": ""})
    text = generator.generate(tmp_path, "[importlinter]\nroot_package = taskloop\n")
    project(tmp_path, {added: ""})
    assert generator.generate(tmp_path, text) != text


@pytest.mark.parametrize("source", [
    "from . import private as alias", "from .private import Thing", "import taskloop.feature.private as alias",
    "from taskloop.feature import private", "from .api import Thing",
])
def test_initializer_bypass_is_rejected(tmp_path: Path, source: str) -> None:
    project(tmp_path, {"feature/__init__.py": source, "feature/private.py": "", "feature/api.py": ""})
    with pytest.raises(AssertionError):
        assert_initializers_are_private(tmp_path)


def test_folder_without_api_still_has_private_modules(tmp_path: Path) -> None:
    project(tmp_path, {"feature/private.py": ""})
    config = configuration(generator.generate(tmp_path, "[importlinter]\nroot_package = taskloop\n"))
    assert values(config, "importlinter:contract:slice-taskloop.feature", "protected_modules") == {"taskloop.feature.private"}


def test_deeper_python_folder_requires_a_layout_decision(tmp_path: Path) -> None:
    project(tmp_path, {"one/two/three/private.py": ""})
    with pytest.raises(ValueError, match="two folder levels"):
        generator.generate(tmp_path, "[importlinter]\nroot_package = taskloop\n")
