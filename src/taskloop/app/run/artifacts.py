"""Files a step, check or tool drops (screenshots, PDFs) are copied, as plain files, into the bead's artifact directory
(`ConfigDir.artifacts`). Symlinks, secret-looking names and big files are skipped; nothing here raises into the engine and no model is
called. The dashboard lists the directory as <img>/<a> links."""
import fnmatch
from pathlib import Path

from atomic_io import atomic_write_bytes

from taskloop.contracts.log import Artifacts
from taskloop.stores.runlog import RunLog

SECRET_NAMES = (".env*", "*.pem", "*.key", "id_*", "*token*", "*secret*")
MAX_BYTES = 25 * 1024 * 1024


def skipped(p: Path) -> bool:
    name = p.name.lower()
    hidden = name.startswith(".") and not name.startswith(".env")
    return p.is_symlink() or not p.is_file() or hidden or any(fnmatch.fnmatch(name, pat) for pat in SECRET_NAMES)


def ingest(src: Path, dest: Path, seen: dict[str, tuple[int, int]] | None = None, skip: frozenset[str] = frozenset()) -> list[str]:
    """Copy each regular file directly under `src` into `dest`; the names copied. A name already there is replaced. With `seen`
    (name -> (mtime, size) of what an earlier call copied) a file that has not changed since is not copied again."""
    got: list[str] = []
    try:
        files = sorted(src.iterdir())
    except OSError:
        return got
    for f in files:
        try:
            st = f.stat()
            unchanged = seen is not None and seen.get(f.name) == (st.st_mtime_ns, st.st_size)
            if skipped(f) or f.name in skip or st.st_size > MAX_BYTES or unchanged:
                continue
            dest.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(dest / f.name, f.read_bytes(), fsync=False)
            got.append(f.name)
            if seen is not None:
                seen[f.name] = (st.st_mtime_ns, st.st_size)
        except OSError:
            continue
    return got


class StepArtifacts:
    """Called as a step ends: copies what the run left in `src` (<worktree>/.task/<bead>/artifacts) and in its attempt folders
    (TL_ARTIFACT_DIR) and, when something new was copied, writes one Artifacts record under that step. Never raises into the engine;
    calls no model."""

    def __init__(self, bead: str, src: Path, dest: Path, log: RunLog, run_dir: Path | None = None) -> None:
        self.bead, self.src, self.dest, self.log, self.run_dir = bead, src, dest, log, run_dir
        self.seen: dict[str, tuple[int, int]] = {}

    def __call__(self, step_id: str, step: str) -> None:
        try:
            names = ingest(self.src, self.dest, self.seen)
            if self.run_dir is not None:  # what a command wrote into its TL_ARTIFACT_DIR (the engine's own check.log stays evidence)
                for d in sorted((self.run_dir / "artifacts").glob("*/attempt-*")):
                    names += ingest(d, self.dest, self.seen, frozenset({"check.log"}))
            if names:
                self.log.emit(Artifacts(id=step_id, step=step, bead=self.bead, names=names))
        except Exception as e:  # pictures are never worth a run
            self.log.warn(f"artifacts: {type(e).__name__}: {e}")


__all__ = ["MAX_BYTES", "SECRET_NAMES", "StepArtifacts", "ingest"]
