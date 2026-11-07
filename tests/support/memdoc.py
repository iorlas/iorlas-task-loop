"""In-memory wire document shared by keyed and checkpoint test stores."""
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

from taskloop.stores.api import AmendDoc
from tlkernel import wire
from tlkernel.docstore import Absent, ForeignVersion, Present, Read, Torn, refusal
from tlkernel.wire import Open, Refused


class MemDoc[T](AmendDoc[T]):
    def __init__(self, cls: type[T]) -> None:
        self.cls = cls
        self.data: Open | None = None

    def read(self) -> Read[T]:
        if self.data is None:
            return Absent()
        path = Path("<memory>")
        try:
            return Present(wire.load(self.cls, self.data))
        except wire.StaleRecord as err:
            return ForeignVersion(path, err.found, err.want)
        except ValueError as err:
            return Torn(path, str(err))

    def get(self) -> T | None:
        r = self.read()
        return r.rec if isinstance(r, Present) else None

    def need(self) -> T | None:
        r = self.read()
        if isinstance(r, (Torn, ForeignVersion)):
            raise Refused(refusal(r))
        return r.rec if isinstance(r, Present) else None

    def write(self, rec: T) -> None:
        self.data = json.loads(json.dumps(wire.dump(rec)))

    def modify(self, fn: Callable[[T], T]) -> bool:
        rec = self.get()
        if rec is None:
            return False
        self.write(fn(rec))
        return True

    def modify_with(self, fn: Callable[[T], T], also: Callable[[sqlite3.Connection | None], None]) -> bool:
        also(None)
        return self.modify(fn)

    def delete(self) -> None:
        self.data = None

