"""Typed document reads shared by file stores and authoritative database rows."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from atomic_io import atomic_write_json

from taskloop.contracts import wire
from taskloop.contracts.wire import Refused


@dataclass(frozen=True)
class Present[T]:
    rec: T


@dataclass(frozen=True)
class Absent:
    """No document was written, or it was deleted."""


@dataclass(frozen=True)
class Torn:
    path: Path
    why: str


@dataclass(frozen=True)
class ForeignVersion:
    path: Path
    found: object
    want: int


type Read[T] = Present[T] | Absent | Torn | ForeignVersion


def refusal(r: Torn | ForeignVersion) -> str:
    if isinstance(r, Torn):
        return f"{r.path} is torn or not a record of this version ({r.why}): fix or delete it; it is not read as empty"
    return f"{r.path} is v{r.found!r}, this install reads v{r.want}: delete it or run the install that wrote it"


class JsonStore[T]:
    """Atomic JSON documents; get is lossy, need refuses an unreadable document."""

    def __init__(self, path: Path, cls: type[T]) -> None:
        self.path = Path(path)
        self.cls = cls

    def decode(self, text: str) -> Read[T]:
        try:
            return Present(wire.load(self.cls, json.loads(text)))
        except wire.StaleRecord as err:
            return ForeignVersion(self.path, err.found, err.want)
        except ValueError as err:
            return Torn(self.path, str(err))

    def read(self) -> Read[T]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return Absent()
        except OSError as err:
            return Torn(self.path, str(err))
        return self.decode(text)

    def get(self) -> T | None:
        r = self.read()
        return r.rec if isinstance(r, Present) else None

    def need(self) -> T | None:
        r = self.read()
        if isinstance(r, (Torn, ForeignVersion)):
            raise Refused(refusal(r))
        return r.rec if isinstance(r, Present) else None

    def write(self, rec: T) -> None:
        atomic_write_json(self.path, wire.dump(rec), indent=1, fsync=False)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class Item[T]:
    start: int
    end: int
    rec: T


@dataclass(frozen=True)
class Page[T]:
    items: list[Item[T]]
    cursor: int
    skipped: int = 0


class Ledger[T](Protocol):
    def append(self, rec: T) -> int: ...
    def read_from(self, offset: int = 0, limit: int | None = None) -> Page[T]: ...
    def tail(self, n: int, before: int | None = None) -> Page[T]: ...
