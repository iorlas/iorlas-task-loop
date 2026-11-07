"""Stage packages expose only their declared public entry points."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SURFACE = {"tlpipeline": ("api", "testing", "contracts")}
PACKAGE_ONLY = {"tlslots": ("api", "testing"), "tlartifacts": ("api",)}


def imported_names(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        return []
    if node.module == package:
        return [f"{package}.{alias.name}" for alias in node.names]
    return [node.module] if node.module else []


def problems(root: Path = ROOT) -> list[str]:
    problems = []
    for folder in ("src", "tests", "dev", "skills", "packages"):
        for path in sorted((root / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            surfaces = SURFACE | PACKAGE_ONLY if folder == "packages" else SURFACE
            for package, allowed in surfaces.items():
                own_folder = root / "packages" / package.removeprefix("tl")
                if path.is_relative_to(own_folder):
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.Import, ast.ImportFrom)):
                        continue
                    names = imported_names(node, package)
                    for name in names:
                        if name == package or (
                            name.startswith(f"{package}.")
                            and name.split(".")[1] not in allowed
                        ):
                            problems.append(f"{path.relative_to(root)}:{node.lineno}: {name}")
    return problems


def test_package_surface():
    assert not (bad := problems()), "Private package imports:\n" + "\n".join(bad)


@pytest.mark.parametrize("location", ["src/consumer", "tests"])
@pytest.mark.parametrize("source,bad", [
    ("import tlslots.pool\n", "tlslots.pool"),
    ("from tlslots import pool\n", "tlslots.pool"),
    ("import tlslots\n", "tlslots"),
    ("from tlslots.pool import Slot\n", "tlslots.pool"),
    ("import tlslots.api\nfrom tlslots.testing import Rig\n", None),
    ("from tlslots import api, testing\n", None),
])
def test_other_packages_use_only_slots_public_surface(tmp_path, location, source, bad):
    path = tmp_path / "packages" / "other" / location / "consumer.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert problems(tmp_path) == (
        [f"{path.relative_to(tmp_path)}:1: {bad}"] if bad else []
    )


@pytest.mark.parametrize("folder", ["src/taskloop", "tests", "dev", "skills", "packages/slots/tests", "packages/slots/src/tlslots"])
def test_slots_internal_imports_remain_allowed_outside_other_packages(tmp_path, folder):
    path = tmp_path / folder / "consumer.py"
    path.parent.mkdir(parents=True)
    path.write_text("from tlslots.pool import Slot\n", encoding="utf-8")
    assert problems(tmp_path) == []
