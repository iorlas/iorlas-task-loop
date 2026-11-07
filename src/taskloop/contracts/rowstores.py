"""The row document stores of factory.db (status, notes, repos index, pin, release result, bad versions, reflect state)."""
from collections.abc import Callable

from taskloop.contracts import paths
from taskloop.contracts.docrows import RowDoc, singleton
from taskloop.contracts.docstore import Absent, Present
from taskloop.contracts.factoryparts import RELEASE_DOCS
from taskloop.contracts.guard import guard
from taskloop.contracts.loop import BadVersions
from taskloop.contracts.reponame import repo_name
from taskloop.contracts.snapshots import (
    Pin,
    ReflectState,
    ReleaseResult,
    RepoEntry,
    ReposIndex,
    SharedNotes,
    StatusSnapshot,
    StatusTried,
)


class StatusStore(RowDoc[StatusSnapshot]):
    def __init__(self, cfg: paths.ConfigDir, quiet: bool = False) -> None:
        super().__init__(singleton(cfg, StatusSnapshot, "snapshot:delegate.status", quiet).docs, "")


class StatusTriedStore(RowDoc[StatusTried]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, StatusTried, "snapshot:delegate.tried").docs, "")


class SharedNotesStore(RowDoc[SharedNotes]):
    def __init__(self, cfg: paths.ConfigDir, repo_key: str) -> None:
        super().__init__(singleton(cfg, SharedNotes, "shared:" + repo_key).docs, "")


class ReposStore:
    """The repos index: every repo `tl` has seen, by name, as the `kv` row `repos` of factory.db. Adding one reads and writes under a lock,
    so two processes never drop a repo. `quiet` (the dashboard): a database that cannot be opened reads as no repos."""

    def __init__(self, cfg: paths.ConfigDir, quiet: bool = False) -> None:
        self.doc = singleton(cfg, ReposIndex, "repos", quiet)
        self.lock = cfg.lock_record("repos", "index")

    def get(self) -> ReposIndex | None:
        return self.doc.get()

    def write(self, rec: ReposIndex) -> None:
        self.doc.write(rec)

    def index(self) -> ReposIndex:
        """The index (empty when there is none). One of another version is an error (ValueError), never read as empty."""
        read = self.doc.read()
        if isinstance(read, Present):
            return read.rec
        if isinstance(read, Absent):
            return ReposIndex()
        raise ValueError(self._refusal())

    def _refusal(self) -> str:
        return ("the repos index row in factory.db is not of this version: delete it; "
                "every tl process registers its repo again")

    def known(self) -> list[str]:
        """The repo folders, oldest first."""
        return [e.path for e in self.index().repos.values()]

    def path_of(self, name: str) -> str:
        """The folder of repo `name`: the name, or the folder when it is one; unknown and ambiguous names are a ValueError with the fix."""
        idx = self.index().repos
        if name in idx:
            return idx[name].path
        short = [n for n in idx if n.rsplit("/", 1)[-1] == name]
        if len(short) == 1:
            return idx[short[0]].path
        if short:
            raise ValueError(f"repo {name!r} is ambiguous ({', '.join(sorted(short))}): give the full owner/name")
        raise ValueError(f"repo {name!r} is not registered: run `tl register` in its folder; known: {', '.join(sorted(idx)) or 'none'}")

    def add(self, path: str, now: float) -> bool:
        """Register `path`; False when it was known. A name another folder holds is a ValueError. Another version is a ValueError too,
        and the file is never overwritten."""
        if path in self.known():
            return False
        name = repo_name(path)
        with guard(self.lock):
            idx = self.index()
            if any(e.path == path for e in idx.repos.values()):
                return False
            if name in idx.repos:
                held = idx.repos[name].path
                raise ValueError(f"repo name {name!r} is taken by {held}: remove that entry (`tl prune` drops a folder that is gone)")
            self.write(idx.replace(repos={**idx.repos, name: RepoEntry(path=path, added=now)}))
            return True

    def drop_missing(self, exists: Callable[[str], bool]) -> list[str]:
        """Drop the entries whose folder `exists` says is gone. -> their names."""
        with guard(self.lock):
            idx = self.index()
            gone = [n for n, e in idx.repos.items() if not exists(e.path)]
            if gone:
                self.write(idx.replace(repos={n: e for n, e in idx.repos.items() if n not in gone}))
            return gone


class PinStore(RowDoc[Pin]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, Pin, "pin", table=RELEASE_DOCS).docs, "")


class ReleaseResultStore(RowDoc[ReleaseResult]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, ReleaseResult, "release:last", table=RELEASE_DOCS).docs, "")


class BadVersionStore(RowDoc[BadVersions]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, BadVersions, "bad-versions").docs, "")


class ReflectStateStore(RowDoc[ReflectState]):
    def __init__(self, cfg: paths.ConfigDir) -> None:
        super().__init__(singleton(cfg, ReflectState, "reflect:digest").docs, "")
