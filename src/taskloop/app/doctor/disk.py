"""`tl doctor --disk`: the config folder's bytes by area, largest first, and its volume's free space; a warning when that runs low."""
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from tlkernel import diskrows, factorydb
from tlkernel.paths import ConfigDir

LOW_FREE: Final = 5 << 30  # bytes free on the volume below which doctor warns
WINDOW_S: Final = 7 * 24 * 3600.0  # the samples a forecast fits: the last week up to the latest
SOON_DAYS: Final = 7  # days to full below which doctor warns


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


def days_to_full(samples: Sequence[tuple[float, int]]) -> float | None:
    """Days until the volume is full: a least-squares line over the samples of the last week, run out from the latest one. None
    with fewer than two samples in the window, or a volume that is not filling."""
    if not samples:
        return None
    last = max(t for t, _ in samples)
    window = [(t, f) for t, f in samples if t >= last - WINDOW_S]
    if len(window) < 2:
        return None
    mean_t = sum(t for t, _ in window) / len(window)
    mean_f = sum(f for _, f in window) / len(window)
    spread = sum((t - mean_t) ** 2 for t, _ in window)
    if spread == 0:
        return None
    slope = sum((t - mean_t) * (f - mean_f) for t, f in window) / spread  # bytes a second
    if slope >= 0:
        return None
    now_free = mean_f + slope * (last - mean_t)  # the fitted line at the latest sample
    return max(now_free, 0) / -slope / 86400


def report(root: Path, free: int, samples: Sequence[tuple[float, int]] = ()) -> list[str]:
    """Lines: a row per top-level entry of `root` that holds bytes (largest first, loose files joined as `other`), `total`, `free`, the
    forecast `~N days to full` when `samples` (time, free bytes) show the volume filling, and a WARN when `free` bytes are under
    LOW_FREE or the forecast is under SOON_DAYS."""
    sizes: dict[str, int] = {}
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            name = entry.name if entry.is_dir() else "other"
            sizes[name] = sizes.get(name, 0) + size_of(entry)
    rows = [f"{name} {mb(n)}" for name, n in sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])) if n]
    out = [*rows, f"total {mb(sum(sizes.values()))}", f"free {gb(free)}"]
    days = days_to_full(samples)
    if days is not None:
        out.append(f"~{round(days)} days to full")
        if days < SOON_DAYS:
            out.append(f"WARN the volume of {root} fills in ~{round(days)} days at the pace of the last week: "
                       "`tl prune` removes run data past the retention age")
    if free < LOW_FREE:
        out.append(f"WARN only {gb(free)} free on the volume of {root}: `tl prune` removes run data past the retention age")
    return out


def read_samples(cfg: ConfigDir) -> list[tuple[float, int]]:
    """The free-space samples the loop has kept; none when there is no database or it cannot be read. Never creates the database."""
    if not cfg.factory_db().exists():
        return []
    try:
        con = factorydb.open_ro(cfg.factory_db())
        if con is None:
            return []
        try:
            return diskrows.samples(con)
        finally:
            con.close()
    except (factorydb.DatabaseError, OSError):
        return []


def record_sample(cfg: ConfigDir, free: int, now: float) -> None:
    """Add the volume's free bytes to the samples (one an hour). An unavailable database keeps nothing; the next pass tries again."""
    con = factorydb.open_rw(cfg.factory_db())
    if con is None:
        return
    try:
        with factorydb.begin_immediate(con):
            diskrows.sample(con, free, now)
    finally:
        con.close()


def sample_volume(cfg: ConfigDir, now: float, say: Callable[[str], None]) -> None:
    """The loop's chore: record the free bytes of the config volume; a failure is said, never raised."""
    try:
        record_sample(cfg, shutil.disk_usage(cfg.root).free, now)
    except Exception as e:
        say(f"loop: disk sample: {e}")
