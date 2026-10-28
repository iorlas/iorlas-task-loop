"""Files a step, check or tool drops (screenshots, PDFs) are copied, as plain files, into the bead's artifact directory
(`ConfigDir.artifacts`). Symlinks, secret-looking names and big files are skipped; nothing here raises into the engine and no model is
called. The dashboard lists the directory as <img>/<a> links."""
import fnmatch
from pathlib import Path

from atomic_io import atomic_write_bytes

SECRET_NAMES = (".env*", "*.pem", "*.key", "id_*", "*token*", "*secret*")
MAX_BYTES = 25 * 1024 * 1024


def skipped(p: Path) -> bool:
    name = p.name.lower()
    hidden = name.startswith(".") and not name.startswith(".env")
    return p.is_symlink() or not p.is_file() or hidden or any(fnmatch.fnmatch(name, pat) for pat in SECRET_NAMES)


def ingest(src: Path, dest: Path) -> list[str]:
    """Copy each regular file directly under `src` into `dest`; the names copied. A name already there is replaced."""
    got: list[str] = []
    try:
        files = sorted(src.iterdir())
    except OSError:
        return got
    for f in files:
        try:
            if skipped(f) or f.stat().st_size > MAX_BYTES:
                continue
            dest.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(dest / f.name, f.read_bytes(), fsync=False)
            got.append(f.name)
        except OSError:
            continue
    return got


__all__ = ["MAX_BYTES", "SECRET_NAMES", "ingest"]
