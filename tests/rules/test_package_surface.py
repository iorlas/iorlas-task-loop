"""Stage packages expose only their declared public entry points."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SURFACE = {"tlpipeline": ("api", "testing", "contracts")}
PACKAGE_ONLY = {"tlartifacts": ("api",)}


def imported_names(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        return []
    if node.module == package:
        return [f"{package}.{alias.name}" for alias in node.names]
    return [node.module] if node.module else []


def test_package_surface():
    problems = []
    for folder in ("src", "tests", "dev", "skills", "packages"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for package, allowed in (SURFACE | (PACKAGE_ONLY if folder == "packages" else {})).items():
                own_folder = ROOT / "packages" / package.removeprefix("tl")
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
                            problems.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
    assert not problems, "Private package imports:\n" + "\n".join(problems)
