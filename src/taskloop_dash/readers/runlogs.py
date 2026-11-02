"""Append-only engine logs, with one cursor and only the latest Beat per path."""

import dataclasses
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from taskloop.contracts import log
from taskloop.contracts.locator import RunBundle
from taskloop.contracts.runlife import shown
from taskloop_dash import jsonl
from taskloop_dash.cache import FileCache
from taskloop_dash.views.runfacts import Run, run_of


@dataclass
class LogTail:
    identity: tuple[int, int]
    size: int = 0
    offset: int = 0
    records: list[log.EngineLog] = field(default_factory=list)
    beat: log.Beat | None = None
    made: Run | None = None


class RunLogs:
    def __init__(self, files: FileCache) -> None:
        self.files = files
        self.lock = threading.Lock()
        self.runs: OrderedDict[str, LogTail] = OrderedDict()

    def typed_run(self, b: RunBundle, now: float) -> Run:
        """Parse new complete lines only; rotation or truncation resets the cursor."""
        path = str(b.log)
        with self.lock:
            try:
                with open(path, "rb") as file:
                    stat = os.fstat(file.fileno())
                    identity = (stat.st_dev, stat.st_ino)
                    tail = self.runs.get(path)
                    if tail is None or tail.identity != identity or stat.st_size < tail.size:
                        tail = LogTail(identity)
                    file.seek(tail.offset)
                    data = file.read()
            except OSError:
                self.runs.pop(path, None)
                return dataclasses.replace(run_of(b.run, [], now), life=shown(b.manifest, now))
            end = data.rfind(b"\n") + 1
            changed = False
            for raw in data[:end].splitlines():
                rec = jsonl.parse(raw)
                if isinstance(rec, log.Beat):
                    tail.beat = rec
                elif rec is not None:
                    tail.records.append(rec)
                changed |= rec is not None
            tail.offset += end
            tail.size = stat.st_size
            if tail.made is None or changed:
                tail.made = run_of(b.run, [*tail.records, *([tail.beat] if tail.beat else [])], now)
            self.runs[path] = tail
            self.runs.move_to_end(path)
            while len(self.runs) > 5000:
                self.runs.popitem(last=False)
            return dataclasses.replace(tail.made, life=shown(b.manifest, now))
