"""RunLog: what the engine calls to record a run. Typed records in, one log out; quiet kinds are logged but not echoed."""
import time
from collections.abc import Callable

from taskloop.contracts import wire
from taskloop.contracts.log import EngineLog, Note, Warn
from taskloop.stores.api import Log


class RunLog:
    def __init__(self, log: Log[EngineLog], echo: Callable[[str], None] | None = None, quiet: frozenset[str] = frozenset(),
                 render: Callable[[EngineLog], str | None] | None = None, clock: Callable[[], float] = time.time,
                 first_id: int = 0) -> None:
        self.log = log
        self.echo = echo
        self.quiet = quiet
        self.render = render  # the console line of a record (None: not shown); default: kind and fields
        self.clock = clock
        self.ids = first_id  # one counter for every prefix, so an id is unique in the file whatever its prefix

    def emit(self, rec: EngineLog) -> int:
        """Append the record (stamped with the time when it has none); echo a line of it unless its kind is quiet. Returns its offset."""
        if not rec.t:
            rec = rec.model_copy(update={"t": self.clock()})
        at = self.log.append(rec)
        if self.echo is not None and rec.kind not in self.quiet:
            line = self.render(rec) if self.render else self.plain(rec)
            if line is not None:
                self.echo(line)
        return at

    def note(self, text: str) -> int:
        return self.emit(Note(text=text))

    def warn(self, text: str) -> int:
        return self.emit(Warn(text=text))

    def next_id(self, prefix: str) -> str:
        """A pair id for the file: the prefix and the next number."""
        self.ids += 1
        return f"{prefix}{int(self.ids)}"

    @staticmethod
    def plain(rec: EngineLog) -> str:
        return "{} {}".format(
            rec.kind, " ".join("{}={}".format(*kv) for kv in wire.dump(rec).items() if kv[0] not in ("v", "kind", "t"))
        )
