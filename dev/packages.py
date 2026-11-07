"""Which workspace packages a change reaches: the changed files, followed up the declared dependency graph of packages/*/pyproject.toml.

    python3 dev/packages.py [--base REV] [--changed PATH ...]    prints the package directory names to test, one per line

A package is reached when a changed file is under it, or when a package it declares as a dependency is reached. A changed file outside every
package (the root pyproject, uv.lock, the justfile, dev/) reaches all of them. The graph is the manifests' (what a package declares is what
its isolated environment contains), never an import scan. Standard library only (docs/design/stage-packages.md section 5)."""
import argparse
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


def reached(root: Path, changed: set[str]) -> list[str]:
    """The directory names of the packages the changed paths reach."""
    graph = members(root)
    folders = {folder: name for name, (folder, _) in graph.items()}
    if any(not path.startswith("packages/") or path.split("/")[1] not in folders for path in changed):
        return sorted(folders)  # a file outside every package: the root config, the lock, the tooling
    out = {path.split("/")[1] for path in changed}
    grew = True
    while grew:
        grew = False
        for folder, deps in graph.values():
            if folder not in out and any(graph[d][0] in out for d in deps):
                out.add(folder)
                grew = True
    return sorted(out)


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
