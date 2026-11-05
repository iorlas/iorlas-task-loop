"""Typed document reads shared by file stores and authoritative database rows."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, override

from any_json_doc import Absent, Doc, ForeignVersion, ForeignVersionError, Present, Read, Torn, refusal

from taskloop.contracts import wire
from taskloop.contracts.wire import Refused

__all__ = ["Absent", "ForeignVersion", "Item", "JsonStore", "Ledger", "Page", "Present", "Read", "Torn", "refusal"]


def _loader[T](cls: type[T]) -> Callable[[object], T]:
    def load(data: object) -> T:
        try:
            return wire.load(cls, data)
        except wire.StaleRecord as err:
            raise ForeignVersionError(err.found, err.want) from err

    return load


class JsonStore[T](Doc[T]):
    """Atomic JSON documents of one wire record; get is lossy, need refuses an unreadable document."""

    def __init__(self, path: Path, cls: type[T]) -> None:
        super().__init__(path, _loader(cls), wire.dump)

    def decode(self, text: str) -> Read[T]:
        try:
            return Present(self._load(json.loads(text)))
        except ForeignVersionError as err:
            return ForeignVersion(self.path, err.found, err.want)
        except ValueError as err:
            return Torn(self.path, str(err))

    @override
    def need(self) -> T | None:
        r = self.read()
        if isinstance(r, (Torn, ForeignVersion)):
            raise Refused(refusal(r))
        return r.rec if isinstance(r, Present) else None


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
