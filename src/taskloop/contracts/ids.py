"""Identifiers: one parser each, no regex."""
import datetime
import hashlib
from itertools import groupby
from pathlib import Path
from typing import Final, NewType, final

BeadId = NewType("BeadId", str)
CheckId = NewType("CheckId", str)  # a check's id in the registry or the plan: never a bead id
TreeSha = NewType("TreeSha", str)  # the hash of a worktree's files (adapters/treehash.py): never a commit sha
STAMP: Final = "%Y%m%d-%H%M%S"
_BEAD_CHARS: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


def parse_bead_id(text: str) -> BeadId:
    """A bead id: starts with a letter or digit, then letters, digits, `_`, `.`, `-`."""
    if not text or not text[0].isascii() or not text[0].isalnum() or not set(text) <= _BEAD_CHARS:
        raise ValueError(f"not a bead id: {text!r}")
    return BeadId(text)


@final
class RunId:
    """`<bead>-YYYYMMDD-HHMMSS`: the run's name and the stem of its files. The stamp is the engine's wall clock."""

    __slots__ = ("bead", "started")

    def __init__(self, bead: BeadId, started: datetime.datetime) -> None:
        self.bead = bead
        self.started = started

    @classmethod
    def parse(cls, text: str) -> RunId:
        parts = text.rsplit("-", 2)
        if len(parts) != 3:
            raise ValueError(f"not a run id: {text!r}")
        try:
            started = datetime.datetime.strptime(f"{parts[1]}-{parts[2]}", STAMP)
        except ValueError:
            raise ValueError(f"not a run id: {text!r}") from None
        return cls(parse_bead_id(parts[0]), started)

    from_wire = parse

    def to_wire(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return f"{self.bead}-{self.started.strftime(STAMP)}"

    def __repr__(self) -> str:
        return f"RunId({self})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RunId) and (self.bead, self.started) == (other.bead, other.started)

    def __hash__(self) -> int:
        return hash((self.bead, self.started))


@final
class Version(tuple[int, ...]):
    """A dotted version as an ordered tuple of ints: `Version.parse("0.23.56") > Version.parse("0.9.1")`."""

    __slots__ = ()

    @classmethod
    def parse(cls, text: str) -> Version:
        parts = text.split(".")
        if not text or not all(p.isascii() and p.isdigit() for p in parts):
            raise ValueError(f"not a version: {text!r}")
        return cls(int(p) for p in parts)

    from_wire = parse

    def to_wire(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return ".".join(str(n) for n in self)


MARKETPLACE: Final = "iorlas-marketplace"  # the only marketplace a plugin cache dir may come from


def repo_key(common_dir: str) -> str:
    """The 12-hex key of a repository: sha1 of its git common dir."""
    return hashlib.sha1(common_dir.encode("utf-8")).hexdigest()[:12]


def loop_key(repo: object) -> str:
    """The key of a repo checkout in the loop's and the slots' files: its folder name and 8 hex of sha1 of its path."""
    return f"{Path(str(repo)).name}-{hashlib.sha1(str(repo).encode()).hexdigest()[:8]}"


def mangle(check_id: CheckId) -> str:
    """The id as an environment name: each run of non-word characters becomes one `_`, upper case. Not injective: the profile load
    refuses two ids that mangle alike (`unity-test`, `unity_test`)."""
    out = []
    for word, run in groupby(check_id, key=lambda ch: ch.isalnum() or ch == "_"):
        out.append("".join(run) if word else "_")
    return "".join(out).upper()
