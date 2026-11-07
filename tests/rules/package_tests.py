"""TESTISO: workspace tests import only their member, declared dependencies, pytest and the standard library."""
import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def normalized(name: str) -> str:
    return name.lower().replace("-", "_")


def dependency_name(requirement: str) -> str:
    return normalized(re.split(r"[\s\[<>=!~;@]", requirement, maxsplit=1)[0])


def member_imports(manifest: Path) -> tuple[str, set[str], set[str]]:
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    project = data["project"]
    roots = {Path(path).name for path in data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]}
    declared = [*project.get("dependencies", []), *data.get("dependency-groups", {}).get("dev", [])]
    deps = {dependency_name(dep) for dep in declared if isinstance(dep, str)}
    return normalized(project["name"]), roots, deps


def imports(path: Path) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name.split(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return sorted(found)


def problems(root: Path = ROOT) -> list[str]:
    manifests = {path: member_imports(path) for path in sorted((root / "packages").glob("*/pyproject.toml"))}
    members = {name: roots for name, roots, _ in manifests.values()}
    found = []
    for manifest, (_, own, deps) in manifests.items():
        tests = manifest.parent / "tests"
        if not tests.is_dir():
            continue
        allowed = own | {"pytest"} | sys.stdlib_module_names
        for dep in deps & members.keys():
            allowed |= members[dep]
        third_party = deps - members.keys()
        for path in sorted(tests.rglob("*.py")):
            for line, name in imports(path):
                if name not in allowed and normalized(name) not in third_party:
                    found.append(f"{path.relative_to(root)}:{line} imports {name} (undeclared in {manifest.relative_to(root)})")
    return found
