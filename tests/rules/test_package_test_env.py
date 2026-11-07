"""Packages with tests must declare their isolated pytest environment."""

import tomllib
from pathlib import Path


def test_packages_with_tests_have_test_environment():
    root = Path(__file__).resolve().parents[2]
    missing = []
    for tests in sorted((root / "packages").glob("*/tests")):
        if not tests.is_dir():
            continue
        manifest = tests.parent / "pyproject.toml"
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        if "dev" not in data.get("dependency-groups", {}):
            missing.append(f"{manifest.relative_to(root)}: missing dev group")
        if "ini_options" not in data.get("tool", {}).get("pytest", {}):
            missing.append(f"{manifest.relative_to(root)}: missing pytest ini")
    assert not missing, "\n".join(missing)
