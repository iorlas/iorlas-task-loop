"""Checkpoint fake: MemDoc cursor and section rows using the kernel's split/join."""
import copy
import sqlite3
from collections.abc import Callable
from pathlib import Path

from tlkernel.checkpoint import SECTION_TYPES, Checkpoint, CursorBody, join, split
from tlkernel.docrows import StaleRevision
from tlkernel.docstore import Absent, ForeignVersion, Present, Read, Torn, refusal
from tlkernel.wire import Rec, Refused
from tltestkit.memdoc import MemDoc


class MemCheckpointDoc:
    """The revisioned AmendDoc face over memory rows."""

    def __init__(self, bead: str) -> None:
        self.bead = bead
        self.cursor = MemDoc(CursorBody)
        self.sections = {name: MemDoc(cls) for name, cls in SECTION_TYPES.items()}
        self.rev: int | None = None

    def revision(self) -> int | None:
        return self.rev

    def read(self) -> Read[Checkpoint]:
        cursor = self.cursor.read()
        if not isinstance(cursor, Present):
            return cursor
        sections: dict[str, Rec] = {}
        for name, doc in self.sections.items():
            section = doc.read()
            if not isinstance(section, Present):
                if isinstance(section, Absent):
                    return Torn(Path("<memory>"), f"missing {name} section")
                return section
            sections[name] = section.rec
        return Present(join(cursor.rec, sections))

    def get(self) -> Checkpoint | None:
        read = self.read()
        return read.rec if isinstance(read, Present) else None

    def need(self) -> Checkpoint | None:
        read = self.read()
        if isinstance(read, (ForeignVersion, Torn)):
            raise Refused(refusal(read))
        return read.rec if isinstance(read, Present) else None

    def write(self, rec: Checkpoint, *, expect_rev: int | None = None) -> None:
        if rec.bead != self.bead:
            raise Refused(f"checkpoint {self.bead}: bead differs: {rec.bead}")
        if expect_rev is not None and self.rev != expect_rev:
            raise StaleRevision(rec.bead)
        cursor, sections = split(rec)
        old_cursor = copy.deepcopy(self.cursor.data)
        old_sections = {name: copy.deepcopy(doc.data) for name, doc in self.sections.items()}
        try:
            self.cursor.write(cursor)
            for name, section in sections.items():
                if self.sections[name].get() != section:
                    self.sections[name].write(section)
        except Exception:
            self.cursor.data = old_cursor
            for name, data in old_sections.items():
                self.sections[name].data = data
            raise
        self.rev = 0 if self.rev is None else self.rev + 1

    def modify(self, fn: Callable[[Checkpoint], Checkpoint], tries: int = 8) -> bool:
        return self._modify(fn, None, tries)

    def modify_with(self, fn: Callable[[Checkpoint], Checkpoint],
                    also: Callable[[sqlite3.Connection | None], None], tries: int = 8) -> bool:
        return self._modify(fn, also, tries)

    def _modify(self, fn: Callable[[Checkpoint], Checkpoint],
                also: Callable[[sqlite3.Connection | None], None] | None, tries: int) -> bool:
        for _ in range(tries):
            rec, rev = self.need(), self.rev
            if rec is None:
                if also is not None:
                    also(None)
                return False
            new = fn(rec)
            try:
                if also is not None:
                    also(None)
                self.write(new, expect_rev=rev)
                return True
            except StaleRevision:
                continue
        raise StaleRevision("<memory>")

    def delete(self) -> None:
        self.cursor.delete()
        for doc in self.sections.values():
            doc.delete()
        self.rev = None


class MemCheckpointRows:
    """Keyed checkpoint rows in memory."""

    def __init__(self) -> None:
        self.docs: dict[str, MemCheckpointDoc] = {}

    def of(self, key: str) -> MemCheckpointDoc:
        return self.docs.setdefault(key, MemCheckpointDoc(key))

    def keys(self) -> list[str]:
        return sorted(key for key, doc in self.docs.items() if doc.cursor.data is not None)

    def read(self, bead: str) -> Checkpoint | None:
        return self.of(bead).need()

    def write(self, ck: Checkpoint, expect_rev: int | None = None) -> None:
        self.of(ck.bead).write(ck, expect_rev=expect_rev)

    def delete(self, bead: str) -> None:
        self.of(bead).delete()
