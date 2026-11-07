"""One line of a run's files as a live event: an engine record (any kind of the EngineLog union, no whitelist) or a line the worker
appended to its call's live file. Every event carries `seq` (file tag + byte offset), `t`, `src` and `kind`."""

from typing import Any

from taskloop_dash.jsonrec import Json
from tlkernel import wire

ENGINE = "engine"


def decode_worker(data: object) -> Json:
    """A worker line is an object with a time and a kind; anything else is not an event."""
    if isinstance(data, dict) and isinstance(data.get("t"), (int, float)) and isinstance(data.get("kind"), str) and data["kind"]:
        return data
    raise ValueError("not a worker event")


def engine_event(record: Any, offset: int) -> Json:
    d = wire.dump(record)
    d.pop("v", None)
    return dict(d, src=ENGINE, seq=f"{ENGINE}:{offset}")


def worker_event(data: Json, tag: str, offset: int) -> Json:
    return dict(data, src=tag, seq=f"{tag}:{offset}")


def rank(event: Json) -> int:
    """Ties in time: the engine first."""
    return 0 if event["src"] == ENGINE else 1
