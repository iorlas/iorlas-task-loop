"""Evidence a run keeps, without a second copy of what it already has: a picture identical to one kept before (this round's, an
earlier round's, an earlier run of the bead) becomes a hard link to it (a copy when the two are on different disks), and a run keeps
at most `cap` bytes of new content, counting what it dropped."""
import filecmp
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

CAP_BYTES = 200 << 20


def twin_of(src: Path, size: int, dirs: Iterable[Path], but: tuple[Path, ...]) -> Path | None:
    """A file under `dirs` with exactly the content of `src` (same size first, then the bytes), never one of `but`."""
    for d in dirs:
        for f in sorted(d.rglob("*")) if d.is_dir() else []:
            try:
                if f not in but and f.is_file() and f.stat().st_size == size and filecmp.cmp(src, f, shallow=False):
                    return f
            except OSError:
                continue
    return None


def inodes(dirs: Iterable[Path]) -> dict[tuple[int, int], int]:
    """{(device, inode): size} of every file under `dirs`: names linked to one file are one entry."""
    found: dict[tuple[int, int], int] = {}
    for d in dirs:
        for f in d.rglob("*") if d.is_dir() else []:
            try:
                st = f.stat()
                if f.is_file():
                    found[(st.st_dev, st.st_ino)] = st.st_size
            except OSError:
                continue
    return found


def used_bytes(mine: Iterable[Path], seen: Iterable[Path] = ()) -> int:
    """Bytes of content only `mine` holds: a file linked to another name counts once, and not at all when an earlier run holds it."""
    others = inodes(seen).keys()
    return sum(size for key, size in inodes(mine).items() if key not in others)


def place(src: Path, dst: Path, twin: Path | None) -> None:
    """`dst` is `src`'s content: a hard link to `twin` when there is one and the disk allows it, else a copy. A file already at
    `dst` is replaced, never written through (it may be another file's inode)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    if twin is not None:
        try:
            os.link(twin, dst)
            return
        except OSError:  # another disk (EXDEV), or a file system without links
            pass
    shutil.copy2(src, dst)


class Keeper:
    """One run's evidence: `mine` are the dirs it writes (their new bytes count against the cap), `seen` also the earlier runs'."""

    def __init__(self, mine: list[Path], seen: list[Path], cap: int = CAP_BYTES) -> None:
        self.mine, self.seen, self.cap, self.dropped = mine, seen, cap, 0

    def keep(self, src: Path, dst: Path) -> bool:
        """False when the file was dropped for the cap (counted in `dropped`); a twin costs nothing and is never dropped."""
        size = src.stat().st_size
        twin = twin_of(src, size, [*self.mine, *self.seen], (src, dst))
        if twin is None and used_bytes(self.mine, self.seen) + size > self.cap:
            self.dropped += 1
            return False
        place(src, dst, twin)
        return True
