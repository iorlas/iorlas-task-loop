"""TESTISO: workspace tests import only their member, declared dependencies, pytest and the standard library."""
import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = {"gate": "tests/checks", "release": "tests/release"}


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

# Shelf copies have no manifest: the one undeclared path (docs/design/workspace.md section 4).
VENDORED = {p.name for p in (ROOT / "skills/task-loop/_vendor").iterdir() if p.is_dir()}


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
        allowed = own | {"pytest"} | sys.stdlib_module_names | VENDORED
        for dep in deps & members.keys():
            allowed |= members[dep]
        third_party = deps - members.keys()
        for path in sorted(tests.rglob("*.py")):
            for line, name in imports(path):
                if name not in allowed and normalized(name) not in third_party:
                    found.append(f"{path.relative_to(root)}:{line} imports {name} (undeclared in {manifest.relative_to(root)})")
        if integration := INTEGRATION.get(manifest.parent.name):
            for path in sorted((root / integration).rglob("*.py")):
                if path.name in {"__init__.py", "conftest.py"}:
                    continue
                if all(name in allowed or normalized(name) in third_party for _, name in imports(path)):
                    folder = manifest.parent.name
                    found.append(f"{path.relative_to(root)}: imports only the {folder} package; move it to packages/{folder}/tests")
    return found
