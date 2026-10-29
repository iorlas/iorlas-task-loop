"""The engine-log views over one FileCache: a run's timeline, its last node, one block's detail, and the facts a task row needs."""

from typing import Any

from taskloop.contracts import log as rec
from taskloop.contracts.runlife import Liveness, liveness
from taskloop_dash import jsonl
from taskloop_dash.cache import FileCache
from taskloop_dash.views import detail
from taskloop_dash.views import timeline as tlv


class RunLogs:
    def __init__(self, files: FileCache) -> None:
        self.files = files
        self.life = FileCache()  # the same logs with their Beat records: what runlife.liveness reads

    def read(self, path: str) -> list[Any]:
        return tlv.read(path, self.files)

    def liveness(self, path: str, now: float) -> Liveness:
        return liveness(self.life.get(path, lambda p: jsonl.records(p, beats=True), []), now)

    def run_timeline(self, path: str, alive: bool = False, now: float | None = None) -> dict[str, Any]:
        return tlv.run_timeline(path, alive=alive, now=now, cache=self.files)

    def last_node(self, path: str) -> Any:
        return tlv.last_node(path, self.files)

    def block_detail(self, path: str, node_id: str | int, k: int = 0) -> dict[str, Any]:
        return detail.block_detail(path, node_id, k, self.files)

    @staticmethod
    def run_start(recs: list[Any]) -> dict[str, str] | None:
        """The run's start as {worktree, slot}; None when the log has none."""
        start = next((r for r in recs if isinstance(r, rec.RunStart)), None)
        return {"worktree": start.worktree, "slot": start.slot or ""} if start else None
