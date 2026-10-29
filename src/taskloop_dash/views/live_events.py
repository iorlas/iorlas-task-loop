"""One line of a run's files as a live event: an engine record (any kind of the EngineLog union, no whitelist) or a line the worker
appended to its call's live file. Every event carries `seq` (file tag + byte offset), `t`, `src` and `k`."""

from typing import Any

from taskloop.contracts import wire

ENGINE = "engine"


def decode_worker(data: object) -> dict:
    """A worker line is an object with a time and a kind; anything else is not an event."""
    if isinstance(data, dict) and isinstance(data.get("t"), (int, float)) and isinstance(data.get("k"), str) and data["k"]:
        return data
    raise ValueError("not a worker event")


def engine_event(record: Any, offset: int) -> dict:
    d = wire.dump(record)
    kind = d.pop("kind")
    d.pop("v", None)
    return dict(d, k=kind, src=ENGINE, seq=f"{ENGINE}:{offset}")


def worker_event(data: dict, tag: str, offset: int) -> dict:
    return dict(data, src=tag, seq=f"{tag}:{offset}")


def rank(event: dict) -> int:
    """Ties in time: the engine first."""
    return 0 if event["src"] == ENGINE else 1
