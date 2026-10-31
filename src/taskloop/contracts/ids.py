"""Identifiers: one parser each, no regex."""
import hashlib
import os
from itertools import groupby
from pathlib import Path
from typing import Annotated, Final, NewType, TypeIs, final

import msgspec

BeadId = NewType("BeadId", str)
CheckId = NewType("CheckId", str)  # a check's id in the registry or the plan: never a bead id
TreeSha = NewType("TreeSha", str)  # the hash of a worktree's files (adapters/treehash.py): never a commit sha
# A bead id as a request body field: msgspec checks the shape when it decodes (a 400 for anything else), so a handler holds a BeadId.
WireBead = Annotated[BeadId, msgspec.Meta(pattern="^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
_BEAD_CHARS: Final = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


def is_bead_id(text: object) -> TypeIs[BeadId]:
    """A bead id: starts with a letter or digit, then letters, digits, `_`, `.`, `-`: never something bd would read as an option.
    A guard: past `if is_bead_id(x)` the value is a BeadId and is not checked again."""
    return isinstance(text, str) and bool(text) and text[0].isascii() and text[0].isalnum() and set(text) <= _BEAD_CHARS


def parse_bead_id(text: str) -> BeadId:
    """`text` as a BeadId, else ValueError."""
    if not is_bead_id(text):
        raise ValueError(f"not a bead id: {text!r}")
    return text


_CROCKFORD: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RUN_ID_LEN: Final = 26  # 10 characters of milliseconds since the epoch, 16 of randomness (ULID's layout)


@final
class RunId:
    """An opaque run id: 26 Crockford base32 characters, the first ten the creation time in milliseconds (ULID), so ids sort by time.
    It names a run's folder and its files and says nothing else: the bead, the repo and the times are the run's manifest."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    @classmethod
    def new(cls, now: float, entropy: bytes | None = None) -> RunId:
        """A fresh id for a run created at `now` (seconds). `entropy` (10 bytes) is for tests; else the OS's random bytes."""
        rnd = int.from_bytes(entropy if entropy is not None else os.urandom(10), "big")
        n = (int(now * 1000) << 80) | rnd
        return cls("".join(_CROCKFORD[(n >> (5 * i)) & 31] for i in reversed(range(_RUN_ID_LEN))))

    @classmethod
    def parse(cls, text: str) -> RunId:
        if len(text) != _RUN_ID_LEN or not set(text) <= set(_CROCKFORD) or text[0] > "7":
            raise ValueError(f"not a run id: {text!r}")
        return cls(text)

    @classmethod
    def of(cls, text: str) -> RunId | None:
        """`parse`, None for a name that is not a run id."""
        try:
            return cls.parse(text)
        except ValueError:
            return None

    from_wire = parse

    def to_wire(self) -> str:
        return self.text

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"RunId({self.text})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RunId) and self.text == other.text

    def __hash__(self) -> int:
        return hash(self.text)

    def __lt__(self, other: RunId) -> bool:
        return self.text < other.text


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
