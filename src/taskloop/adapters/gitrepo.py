"""A checkout's git folders, read from the file system (no git process): the pin that makes git act on that checkout, the repo's main
checkout, whether two paths are one folder."""

import os
import re
from pathlib import Path

Sig = tuple[int, ...] | None
Dirs = tuple[Path, Path, Path]  # git dir, common dir, the `.git` entry of the checkout


def pinned_env(path: str | Path) -> dict[str, str]:
    """GIT_DIR and GIT_WORK_TREE of the checkout at `path` (its nearest parent with a .git), read from its own `.git`
    (a slot's `.git` file says `gitdir: <its dir under the repo's .git/worktrees>`). With both set git ignores the
    repo's shared config: a core.worktree written into .git/config (lifesim-1mm) pointed every slot at another folder.
    {} when `path` is no checkout."""
    p = Path(path).resolve()
    for d in (p, *p.parents):
        g = d / ".git"
        if g.is_dir():
            return {"GIT_DIR": str(g), "GIT_WORK_TREE": str(d)}
        if g.is_file():
            try:
                m = re.match(r"gitdir:\s*(.+)", g.read_text(encoding="utf-8", errors="replace").strip())
            except OSError:
                return {}
            return {"GIT_DIR": str((d / m.group(1)).resolve()), "GIT_WORK_TREE": str(d)} if m else {}
    return {}


def sig(path: str | Path) -> Sig:
    """What a file is now, as the file system says: (inode, dev, mtime ns, size); None when it is missing. A ref or lock file is
    replaced by a rename, so a changed ref always changes this."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_dev, st.st_mtime_ns, st.st_size)


def is_dir_sig(p: str | Path) -> Sig:
    """A `.git` directory changes its mtime with every lock file; only which directory it is counts. A `.git` file (a slot) is stable."""
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (st.st_ino, st.st_dev) if os.path.isdir(p) else (st.st_ino, st.st_dev, st.st_mtime_ns, st.st_size)


def common_of(cwd: str | Path) -> Path | None:
    """The git dir the checkout at `cwd` shares with its worktrees, read from its `.git`; None when `cwd` is no checkout."""
    gd = pinned_env(cwd).get("GIT_DIR")
    if not gd:
        return None
    gd_path = Path(gd)
    try:
        return (gd_path / (gd_path / "commondir").read_text(encoding="utf-8", errors="replace").strip()).resolve()
    except OSError:
        return gd_path


def git_dirs(cwd: str | Path) -> Dirs | None:
    """The dirs of a plain checkout read from the file system, or None when `cwd` is none or uses a ref backend this reads nothing of."""
    common = common_of(cwd)
    if common is None or (common / "reftable").exists():
        return None
    pin = pinned_env(cwd)
    return Path(pin["GIT_DIR"]), common, Path(pin["GIT_WORK_TREE"]) / ".git"


def repo_root(cwd: str | Path | None = None) -> str:
    """The main checkout of the repo (shared by all its worktrees), so every worktree maps to one repo; `cwd` itself when it is none."""
    here = cwd or os.getcwd()
    common = common_of(here)
    if common is not None:
        return str(common.parent if common.name == ".git" else common)
    return str(Path(here).resolve())


def same_dir(a: object, b: object) -> bool:
    """The same folder: os.path.samefile, realpath equality when either path is missing."""
    try:
        return os.path.samefile(str(a), str(b))
    except OSError:
        return os.path.realpath(str(a)) == os.path.realpath(str(b))
