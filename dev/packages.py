"""Which workspace packages a change reaches: the changed files, followed up the declared dependency graph of packages/*/pyproject.toml.

    python3 dev/packages.py [--base REV] [--changed PATH ...]    prints the package directory names to test, one per line

A changed file always reaches its own package; only public changes reach dependents transitively. With src/*/api.py, public surface is that
api.py, contracts/ contents and top-level src package testing.py; without api.py every file is public. A changed file outside every
package (the root pyproject, uv.lock, the justfile, dev/) reaches all ordinary members; SCOPED members require their own inputs. The graph
is the manifests' (what a package declares is what
its isolated environment contains), never an import scan. Standard library only (docs/design/stage-packages.md section 5)."""
import argparse
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# These members opt out of the root-file fanout. Their own paths and declared
# dependencies still propagate normally; extra inputs are explicit prefixes.
SCOPED = {"delegate": ("src/delegate/", "tests/delegate/", "skills/task-loop/_vendor/", "dev/vendor.json", "packages/testkit/")}


def members(root: Path) -> dict[str, tuple[str, set[str]]]:
    """{project name: (directory name, names of the workspace members it declares)}."""
    found = {}
    for manifest in sorted((root / "packages").glob("*/pyproject.toml")):
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        project = data["project"]
        declared = [*project.get("dependencies", []), *data.get("dependency-groups", {}).get("dev", [])]
        names = {re.split(r"[\s\[<>=!~;]", d, maxsplit=1)[0] for d in declared if isinstance(d, str)}
        found[project["name"]] = (manifest.parent.name, names)
    return {name: (folder, deps & found.keys()) for name, (folder, deps) in found.items()}


def public(root: Path, folder: str, path: str) -> bool:
    """Whether a changed path is public surface for its workspace package."""
    package = root / "packages" / folder
    apis = list(package.glob("src/*/api.py"))
    if not apis:
        return True
    relative = Path(path).relative_to(Path("packages") / folder)
    return ("contracts" in relative.parts[:-1]
            or any(root / path in (api, api.parent / "testing.py") for api in apis))


def reached(root: Path, changed: set[str]) -> list[str]:
    """The directory names of the packages the changed paths reach."""
    graph = members(root)
    folders = {folder: name for name, (folder, _) in graph.items()}
    outside = any(not path.startswith("packages/") or path.split("/")[1] not in folders for path in changed)
    out = {path.split("/")[1] for path in changed if path.startswith("packages/") and path.split("/")[1] in folders}
    out |= {folder for folder, paths in SCOPED.items() if folder in folders and any(p.startswith(paths) for p in changed)}
    propagated = {path.split("/")[1] for path in changed if path.startswith("packages/") and path.split("/")[1] in folders
                  and public(root, path.split("/")[1], path)}
    grew = True
    while grew:
        grew = False
        for folder, deps in graph.values():
            if folder not in propagated and any(graph[d][0] in propagated for d in deps):
                propagated.add(folder)
                grew = True
    return sorted(out | propagated | (folders.keys() - SCOPED.keys() if outside else set()))


def changed_since(root: Path, base: str) -> set[str]:
    def run(*argv: str) -> set[str]:
        return set(subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=False).stdout.split())
    return run("diff", "--name-only", "--no-renames", base) | run("ls-files", "--others", "--exclude-standard")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base")
    ap.add_argument("--changed", nargs="*")
    args = ap.parse_args()
    if args.changed is None:
        base = args.base or subprocess.run(["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT, capture_output=True, text=True,
                                           check=False).stdout.strip() or "HEAD"
        changed = changed_since(ROOT, base)
    else:
        changed = set(args.changed)
    print("\n".join(reached(ROOT, changed)))


if __name__ == "__main__":
    main()
