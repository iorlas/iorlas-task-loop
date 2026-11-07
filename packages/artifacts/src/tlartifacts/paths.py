"""Paths owned by tlartifacts."""
from pathlib import Path

from tlkernel.paths import RunFiles


def check_dirs(run_dir: Path | str) -> list[tuple[int, Path]]:
    """(run attempt, <step> folder) of every step that kept anything, oldest run attempt first."""
    found: list[tuple[int, Path]] = []
    for a in sorted(RunFiles(run_dir).attempts().glob("*-attempt-*/artifacts")):
        n = a.parent.name.rpartition("-attempt-")[2]
        found += [(int(n), d) for d in sorted(a.iterdir()) if d.is_dir()] if n.isdigit() else []
    return sorted(found, key=lambda x: x[0])
