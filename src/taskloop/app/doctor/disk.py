"""`tl doctor --disk`: the config folder's bytes by area, largest first, and its volume's free space; a warning when that runs low."""
from pathlib import Path
from typing import Final

LOW_FREE: Final = 5 << 30  # bytes free on the volume below which doctor warns


def size_of(path: Path) -> int:
    """Bytes under `path` (the file itself, or every file below); 0 for a path that is not there. A file that goes meanwhile counts 0."""
    if path.is_file():
        return path.stat().st_size
    total = 0
    for entry in path.rglob("*") if path.is_dir() else ():
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def mb(n: int) -> str:
    return f"{n / (1 << 20):.1f} MB"


def gb(n: int) -> str:
    return f"{n / (1 << 30):.1f} GB"


def report(root: Path, free: int) -> list[str]:
    """Lines: a row per top-level entry of `root` that holds bytes (largest first, loose files joined as `other`), `total`, `free`, and a
    WARN when `free` bytes are under LOW_FREE."""
    sizes: dict[str, int] = {}
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            name = entry.name if entry.is_dir() else "other"
            sizes[name] = sizes.get(name, 0) + size_of(entry)
    rows = [f"{name} {mb(n)}" for name, n in sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])) if n]
    out = [*rows, f"total {mb(sum(sizes.values()))}", f"free {gb(free)}"]
    if free < LOW_FREE:
        out.append(f"WARN only {gb(free)} free on the volume of {root}: `tl prune` removes run data past the retention age")
    return out
