"""The ledger: facts appended to a JSON-lines file, folded on demand. The clock is always the caller's."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import TYPE_CHECKING

from any_breaker.fact import Fact
from any_breaker.state import State

if TYPE_CHECKING:
    from pathlib import Path

    from any_breaker.breaker import Breaker, View


class Ledger:
    """`record` appends one fact; `allow` answers for a key at a time. The state is a cache, folded from the file's unread tail
    on each call, and rebuilt from the whole file when the file shrinks. A line that does not parse is skipped, never fatal."""

    def __init__(self, breaker: Breaker, path: Path) -> None:
        self.breaker = breaker
        self.path = path
        self._state = State()
        self._offset = 0

    def record(self, fact: Fact) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(fact), separators=(",", ":")) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode())  # one write, so concurrent appenders interleave by whole line
        finally:
            os.close(fd)

    def allow(self, key: str, now: float) -> View:
        return self.breaker.view(self.state(), key, now)

    def state(self) -> State:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            self._state, self._offset = State(), 0
            return self._state
        if size < self._offset:
            self._state, self._offset = State(), 0
        if size > self._offset:
            with self.path.open("rb") as fh:
                fh.seek(self._offset)
                chunk = fh.read(size - self._offset)
            end = chunk.rfind(b"\n") + 1  # a half-written last line waits for the next call
            self._offset += end
            self._state = self.breaker.fold(_facts(chunk[:end]), self._state)
        return self._state


def _facts(chunk: bytes) -> list[Fact]:
    out: list[Fact] = []
    for line in chunk.decode("utf-8", "replace").splitlines():
        try:
            out.append(Fact(**json.loads(line)))
        except (ValueError, TypeError):
            continue
    return out
