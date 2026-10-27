"""RunLog: what the engine calls to record a run. Typed records in, one log out; quiet kinds are logged but not echoed."""
from collections.abc import Callable

from taskloop.contracts import codec
from taskloop.contracts.log import EngineLog
from taskloop.stores.api import Log


class RunLog:
    def __init__(self, log: Log[EngineLog], echo: Callable[[str], None] | None = None, quiet: frozenset[str] = frozenset()) -> None:
        self.log = log
        self.echo = echo
        self.quiet = quiet

    def emit(self, rec: EngineLog) -> int:
        """Append the record; echo a one-line form of it unless its kind is quiet. Returns its offset."""
        at = self.log.append(rec)
        kind = codec.to_json(rec)["kind"]
        if self.echo is not None and kind not in self.quiet:
            self.echo("%s %s" % (kind, " ".join("%s=%s" % kv for kv in codec.to_json(rec).items() if kv[0] not in ("v", "kind", "t"))))
        return at
