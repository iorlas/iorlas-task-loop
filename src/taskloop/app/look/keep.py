"""Evidence a run keeps, without a second copy of what it already has: a picture identical to one kept before (this round's, an
earlier round's, an earlier run of the bead) becomes a hard link to it (a copy when the two are on different disks), and a run keeps
at most `cap` bytes of new content, counting what it dropped."""
import filecmp
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

CAP_BYTES = 200 << 20


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
    """One run's evidence: `mine` are the dirs it writes (their new bytes count against the cap), `seen` also the earlier runs'.
    The dirs are walked once, here; `keep` then looks a twin up by size and keeps the index and the byte total current."""

    def __init__(self, mine: list[Path], seen: list[Path], cap: int = CAP_BYTES) -> None:
        self.mine, self.seen, self.cap, self.dropped = mine, seen, cap, 0
        self.by_size: dict[int, list[Path]] = {}
        self.mine_keys: dict[tuple[int, int], int] = {}
        self.seen_keys: set[tuple[int, int]] = set()
        for d in seen:  # earlier runs first: what they hold is not this run's bytes
            for f in d.rglob("*") if d.is_dir() else []:
                st = self.stat(f)
                if st is not None:
                    self.by_size.setdefault(st.st_size, []).append(f)
                    self.seen_keys.add((st.st_dev, st.st_ino))
        for d in mine:
            for f in d.rglob("*") if d.is_dir() else []:
                st = self.stat(f)
                if st is not None:
                    self.by_size.setdefault(st.st_size, []).append(f)
                    if (st.st_dev, st.st_ino) not in self.seen_keys:
                        self.mine_keys[(st.st_dev, st.st_ino)] = st.st_size
        self.used = sum(self.mine_keys.values())

    @staticmethod
    def stat(f: Path) -> os.stat_result | None:
        try:
            st = f.stat()
        except OSError:
            return None
        return st if f.is_file() else None

    def twin(self, src: Path, size: int, dst: Path) -> Path | None:
        for f in self.by_size.get(size, []):
            try:
                if f not in (src, dst) and filecmp.cmp(src, f, shallow=False):
                    return f
            except OSError:
                continue
        return None

    def forget(self, dst: Path) -> None:
        """`dst` is about to be replaced: its name leaves the index, and its bytes the total when nothing else names that file."""
        st = self.stat(dst)
        if st is None:
            return
        names = self.by_size.get(st.st_size, [])
        if dst in names:
            names.remove(dst)
        if st.st_nlink == 1 and self.mine_keys.pop((st.st_dev, st.st_ino), None) is not None:
            self.used -= st.st_size

    def keep(self, src: Path, dst: Path) -> bool:
        """False when the file was dropped for the cap (counted in `dropped`); a twin costs nothing and is never dropped."""
        size = src.stat().st_size
        twin = self.twin(src, size, dst)
        self.forget(dst)
        if twin is None and self.used + size > self.cap:
            self.dropped += 1
            return False
        place(src, dst, twin)
        st = self.stat(dst)
        if st is not None:
            self.by_size.setdefault(st.st_size, []).append(dst)
            key = (st.st_dev, st.st_ino)
            if key not in self.mine_keys and key not in self.seen_keys:
                self.mine_keys[key] = st.st_size
                self.used += st.st_size
        return True
