"""One git command's world: the repo it runs in, its arguments, its output."""
import hashlib
from dataclasses import dataclass, field
from typing import Any

from .model import Fail, Repo, Snap, W


@dataclass
class Ctx:
    repo: Repo | None
    args: list[str]
    env: dict[str, str]
    cwd: str
    stdin: bytes = b""
    opts: dict[str, str] = field(default_factory=dict)  # git -c key=value
    out: bytearray = field(default_factory=bytearray)
    err: list[str] = field(default_factory=list)

    def say(self, text: str = "", end: str = "\n") -> None:
        self.out += (text + end).encode()

    def raw(self, data: bytes) -> None:
        self.out += data

    @property
    def r(self) -> Repo:
        if self.repo is None:
            raise Fail("fatal: not a git repository (or any of the parent directories): .git", 128)
        return self.repo

    def index_key(self) -> str:
        return self.env.get("GIT_INDEX_FILE") or str(self.r.git / "index")

    def index(self) -> Snap:
        k = self.index_key()
        return dict(W.index[k]) if k in W.index else dict(self.r.head_snap())

    def set_index(self, snap: Snap) -> None:
        W.index[self.index_key()] = dict(snap)

    def revs(self, names: list[str]) -> tuple[list[str], list[str]]:
        """(include, exclude) shas of rev arguments: `A..B`, `^A` and plain names."""
        inc: list[str] = []
        exc: list[str] = []
        for n in names:
            lo, dots, hi = n.partition("..")
            single = [(n[1:], True)] if n.startswith("^") else [(n, False)]
            parts = [(lo, True), (hi or "HEAD", False)] if dots else single
            for name, neg in parts:
                if not name:
                    continue
                sha = self.r.resolve(name)
                if sha is None:
                    raise Fail(f"fatal: bad revision '{name}'", 128)
                (exc if neg else inc).append(sha)
        return inc, exc


def blob(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def flags(args: list[str]) -> tuple[list[str], list[str]]:
    """(the dash words, the rest) of arguments, up to a `--`; what follows `--` is returned after a "--" in the rest."""
    fl: list[str] = []
    rest: list[str] = []
    for i, a in enumerate(args):
        if a == "--":
            rest += args[i:]
            break
        (fl if a.startswith("-") and len(a) > 1 else rest).append(a)
    return fl, rest


Handler = Any
