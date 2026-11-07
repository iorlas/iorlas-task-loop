"""Select a stage's tests and its forward dependencies' contracts for the developer inner loop."""

import argparse
import ast
from pathlib import Path

from importgraph import targets_of


def closure(root: Path, stage: str) -> set[str]:
    """Return the other app stages transitively imported by any module of this stage."""
    app = root / "src/taskloop/app"
    stages = {p.name for p in app.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    if stage not in stages:
        raise ValueError(f"Unknown stage {stage!r}; known stages: {', '.join(sorted(stages))}")
    edges: dict[str, set[str]] = {name: set() for name in stages}
    for name in stages:
        for path in (app / name).rglob("*.py"):
            parts = path.relative_to(root / "src").with_suffix("").parts
            package = parts[-1] == "__init__"
            module = ".".join(parts[:-1] if package else parts)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for target in targets_of(module, tree, {module} if package else set()):
                imported = target.split(".")
                if imported[:2] == ["taskloop", "app"] and len(imported) > 2 and imported[2] in stages:
                    edges[name].add(imported[2])
    reached = {stage}
    pending = [stage]
    while pending:
        for dependency in edges[pending.pop()] - reached:
            reached.add(dependency)
            pending.append(dependency)
    return reached - {stage}


def selection(root: Path, stage: str) -> list[str]:
    """Return existing test folders, own tests first and dependency contracts sorted."""
    dependencies = closure(root, stage)
    paths = [f"tests/{stage}", *(f"tests/{name}/contract" for name in sorted(dependencies))]
    return [path for path in paths if (root / path).is_dir()]


def main(argv: list[str] | None = None, *, root: Path | None = None) -> None:
    """Print the selection, reporting an unknown stage as a usage error."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage")
    args = parser.parse_args(argv)
    try:
        paths = selection(root if root is not None else Path(__file__).resolve().parent.parent, args.stage)
    except ValueError as error:
        parser.error(str(error))
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
