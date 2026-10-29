"""Which install the loop runs on, and the moves between installs.

The target is the version `installed_plugins.json` names (the owner's `tl pin` wins over it); without a readable entry, the
highest version dir above the running one. A dir that is not installed is never a target. Nothing is tested before a move: a
move that breaks soon after goes back to the old install, and that version is remembered (bad-versions.json) for as long as
the install is the one that broke."""
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from taskloop.contracts import paths
from taskloop.contracts.loop import BadVersion, BadVersions
from taskloop.contracts.stores import JsonStore

CORE = ("tl.py",)


def version_key(name: str) -> tuple[int, ...] | None:
    """(1, 2, 3) for a version dir name like 0.23.6; None for anything else (a dev checkout, a cache scrap)."""
    parts = name.split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else None


@dataclass(frozen=True)
class Target:
    version: str
    dir: Path


def install_key(d: Path) -> str:
    """Size and mtime of the install's core files and its src tree: a version re-installed under the same number differs."""
    files = [d / "skills" / "task-loop" / f for f in CORE]
    files += sorted((d / "src").rglob("*.py"))
    out = []
    for f in files:
        try:
            st = f.stat()
        except OSError:
            return ""
        out.append(f"{st.st_size}:{st.st_mtime_ns}")
    return ",".join(out)


class Installs:
    def __init__(self, cfg: paths.ConfigDir, root: Path, installed: Callable[[], str], pinned: Callable[[], str],
                 now: Callable[[], float] = time.time) -> None:
        self.root, self.installed, self.pinned = root, installed, pinned  # root: the running install's dir
        self.now = now
        self.bad = JsonStore(cfg.bad_versions(), BadVersions)
        self.dangling = ""  # the installed entry whose dir is gone, set by the last target() that fell through to the highest dir

    @property
    def mine(self) -> str:
        return self.root.name

    def refused(self) -> dict[str, str]:
        """{version: why} of the installs bad-versions.json refuses: an entry holds while the install's key is the recorded
        one (an entry without a key holds for good)."""
        doc = self.bad.read()
        return {e.version: e.why for e in (doc.entries if doc else [])
                if not e.key or e.key == install_key(self.root.parent / e.version)}

    def record_bad(self, version: str, why: str) -> None:
        doc = self.bad.read()
        keep = [e for e in (doc.entries if doc else []) if e.version != version]
        key = install_key(self.root.parent / version)
        keep.append(BadVersion(version=version, why=why[:400], t=self.now(), seen_by=self.mine, key=key))
        self.bad.write(BadVersions(entries=keep))

    def target(self, skip: set[str] | frozenset[str] = frozenset()) -> tuple[str, Path] | None:
        """(version, dir) the loop should be on when that is not the running one."""
        mine = version_key(self.mine)
        if mine is None:  # a dev checkout never moves
            return None
        skip = set(skip) | set(self.refused())
        pinned = self.pinned()
        want = pinned or self.installed()
        self.dangling = want if want and not pinned and not (self.root.parent / want).is_dir() else ""
        if want and (pinned or (self.root.parent / want).is_dir()):  # a pin is strict; an installed entry whose dir is gone falls through
            d = self.root.parent / want
            k = version_key(want)
            return (want, d) if k is not None and k != mine and d.is_dir() and want not in skip else None
        best: tuple[tuple[int, ...], Path] | None = None
        for d in self.root.parent.iterdir():
            k = version_key(d.name)
            if k and k > mine and d.name not in skip and d.is_dir() and (best is None or k > best[0]):
                best = (k, d)
        return (best[1].name, best[1]) if best else None

    def move_to(self, skip: set[str] | frozenset[str] = frozenset()) -> Target | None:
        """The install to move to, or None."""
        found = self.target(skip)
        return Target(found[0], found[1]) if found else None

    def previous(self, before: str) -> str:
        """The highest installed version below `before` ("" when none)."""
        k = version_key(before)
        below = [(v, d.name) for d in self.root.parent.iterdir() if (v := version_key(d.name)) and k and v < k and d.is_dir()]
        return max(below)[1] if below else ""
