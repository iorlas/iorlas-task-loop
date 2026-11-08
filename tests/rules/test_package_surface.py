"""Stage packages expose only their declared public entry points."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SURFACE = {"tlareas": ("policy", "testing"), "tlpipeline": ("api", "testing", "contracts")}
PACKAGE_ONLY = {
    # api and the leaf modules tlwork and tlrelease already import (tl-e5t0.84): routing them through api.py would load land's evidence,
    # host and ports into every plan, review, write and release closure (+5 to +27 files per stage), so the guard names the leaves instead
    "tlgate": ("api", "testing", "contracts", "evidence", "authorization", "cache", "domain.planref", "domain.lint", "domain.affinity",
               "domain.names", "domain.inputs", "domain.specs", "domain.writer_split"),
    "tlslots": ("api", "testing"),
    "tlasks": ("api", "testing", "contracts"),
    "tlartifacts": ("api",),
    "tlwork": ("api", "testing"),
}


def imported_names(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        return []
    if node.module and (node.module == package or node.module.startswith(f"{package}.domain")):
        return [f"{node.module}.{alias.name}" for alias in node.names]
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
                            and not any(name == f"{package}.{a}" or name.startswith(f"{package}.{a}.") for a in allowed)
                        ):
                            problems.append(f"{path.relative_to(root)}:{node.lineno}: {name}")
    return problems


def test_package_surface():
    assert not (bad := problems()), "Private package imports:\n" + "\n".join(bad)


@pytest.mark.parametrize("location", ["src/consumer", "tests"])
@pytest.mark.parametrize("package,source,bad", [
    (package, source, bad)
    for package in ("tlslots", "tlasks")
    for source, bad in [
        ("import {package}.pool\n", "{package}.pool"),
        ("from {package} import pool\n", "{package}.pool"),
        ("import {package}\n", "{package}"),
        ("from {package}.pool import Slot\n", "{package}.pool"),
        ("import {package}.api\nfrom {package}.testing import Rig\n", None),
        ("from {package} import api, testing\n", None),
    ]
] + [
    ("tlasks", "from tlasks.contracts.records import Asking\n", None),
    ("tlasks", "from tlasks import contracts\n", None),
    ("tlgate", "from tlgate.runner import run\n", "tlgate.runner"),
    ("tlgate", "from tlgate.domain import lint, planref\nfrom tlgate.domain.specs import repo_check\nfrom tlgate import evidence\n", None),
    ("tlgate", "from tlgate.domain import checks\n", "tlgate.domain.checks"),
    ("tlgate", "from tlgate.domain.lintx import plan\n", "tlgate.domain.lintx.plan"),
])
def test_other_packages_use_only_public_surface(tmp_path, location, package, source, bad):
    source = source.format(package=package)
    bad = bad.format(package=package) if bad else None
    path = tmp_path / "packages" / "other" / location / "consumer.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert problems(tmp_path) == (
        [f"{path.relative_to(tmp_path)}:1: {bad}"] if bad else []
    )


@pytest.mark.parametrize("package", ["tlslots", "tlasks"])
@pytest.mark.parametrize("folder", ["src/taskloop", "tests", "dev", "skills", "packages/{owner}/tests", "packages/{owner}/src/{package}"])
def test_internal_imports_remain_allowed_outside_other_packages(tmp_path, folder, package):
    folder = folder.format(owner=package.removeprefix("tl"), package=package)
    path = tmp_path / folder / "consumer.py"
    path.parent.mkdir(parents=True)
    path.write_text(f"from {package}.pool import Slot\n", encoding="utf-8")
    assert problems(tmp_path) == []
