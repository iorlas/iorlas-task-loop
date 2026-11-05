"""One JSON document per file, replaced atomically and read as one of four states.

``Doc.read()`` never guesses: a file that is there but unusable is ``Torn`` (half written, bad JSON, wrong shape, unreadable)
or ``ForeignVersion`` (another install's schema), never "empty". The caller decides; ``get`` is the lossy view for caches,
``need`` the strict one. The record type is the host's: it passes ``load`` (JSON value -> record) and ``dump`` (record -> JSON
value). ``load`` raises ``ValueError`` for a bad shape and :class:`ForeignVersionError` for a record of another version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from atomic_io import atomic_write_json

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "Absent",
    "Doc",
    "DocSet",
    "ForeignVersion",
    "ForeignVersionError",
    "Present",
    "Read",
    "RefusedError",
    "Torn",
    "refusal",
]


class RefusedError(ValueError):
    """``need`` met a file that is there and cannot be read; the message names the file."""


class ForeignVersionError(ValueError):
    """Raised by a host's ``load`` for a record whose version is not the one this install reads."""

    def __init__(self, found: object, want: int) -> None:
        super().__init__(f"version {found!r}, want {want}")
        self.found = found
        self.want = want


@dataclass(frozen=True)
class Present[T]:
    rec: T


@dataclass(frozen=True)
class Absent:
    """No file (nothing was ever written, or it was deleted)."""


@dataclass(frozen=True)
class Torn:
    """A file that is there and is not a record: half written, bad JSON, a wrong shape, or unreadable.

    ``why`` is the underlying error text for a human (it goes into the ``need`` message). Callers branch on the state
    (Torn vs ForeignVersion), never on ``why``: the causes are the stdlib's and the host's own, with no closed set to type.
    """

    path: Path
    why: str


@dataclass(frozen=True)
class ForeignVersion:
    """A record of another version (an older or newer install wrote it): never migrated, never read as empty."""

    path: Path
    found: object
    want: int


type Read[T] = Present[T] | Absent | Torn | ForeignVersion


def refusal(r: Torn | ForeignVersion) -> str:
    if isinstance(r, Torn):
        return f"{r.path} is torn or not a record of this version ({r.why}): fix or delete it; it is not read as empty"
    return f"{r.path} is v{r.found!r}, this install reads v{r.want}: delete it or run the install that wrote it"


def _same[T](value: T) -> T:
    return value


class Doc[T]:
    """One JSON document (indent 1), replaced atomically: a reader sees the old file or the new one, never half."""

    def __init__(
        self,
        path: Path,
        load: Callable[[Any], T] = _same,
        dump: Callable[[T], Any] = _same,
        *,
        fsync: bool = False,
    ) -> None:
        self.path = Path(path)
        self._load = load
        self._dump = dump
        self._fsync = fsync

    def read(self) -> Read[T]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Absent()
        except (OSError, ValueError) as err:  # unreadable, or not UTF-8
            return Torn(self.path, str(err))
        try:
            return Present(self._load(json.loads(text)))
        except ForeignVersionError as err:
            return ForeignVersion(self.path, err.found, err.want)
        except ValueError as err:  # bad JSON, a host's shape refusal
            return Torn(self.path, str(err))

    def get(self) -> T | None:
        """The record, None for anything else (Absent, Torn, ForeignVersion): for files that can be derived again."""
        r = self.read()
        return r.rec if isinstance(r, Present) else None

    def need(self) -> T | None:
        """The record, None when there is no file; RefusedError (naming the file) when one is there and cannot be read."""
        r = self.read()
        if isinstance(r, (Torn, ForeignVersion)):
            raise RefusedError(refusal(r))
        return r.rec if isinstance(r, Present) else None

    def write(self, rec: T) -> None:
        atomic_write_json(self.path, self._dump(rec), indent=1, fsync=self._fsync)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


class DocSet[T]:
    """One :class:`Doc` per key, kept as ``folder / (key + suffix)``; ``keys()`` lists the folder.

    A flat folder with one suffix; a key is a file stem (no path separator). A layout that is not that is several
    ``Doc``s, not a ``DocSet``.
    """

    def __init__(
        self,
        folder: Path,
        suffix: str = ".json",
        load: Callable[[Any], T] = _same,
        dump: Callable[[T], Any] = _same,
        *,
        fsync: bool = False,
    ) -> None:
        if not suffix.startswith(".") or "/" in suffix:
            msg = f"suffix must be a dot extension such as '.json', got {suffix!r}"
            raise ValueError(msg)
        self._folder = Path(folder)
        self._suffix = suffix
        self._load = load
        self._dump = dump
        self._fsync = fsync

    def of(self, key: str) -> Doc[T]:
        if not key or "/" in key or key.startswith("."):
            msg = f"key must be a plain file stem, got {key!r}"
            raise ValueError(msg)
        return Doc(self._folder / (key + self._suffix), self._load, self._dump, fsync=self._fsync)

    def keys(self) -> list[str]:
        """Keys that have a file; dot-files (a writer's leftover temp) are not keys."""
        try:
            names = [p.name for p in self._folder.iterdir()]
        except OSError:
            return []
        return sorted(n[: -len(self._suffix)] for n in names if n.endswith(self._suffix) and not n.startswith("."))
