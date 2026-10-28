"""The engine-log views over one FileCache: a run's timeline, its last node, one block's detail, and the facts a task row needs."""

from typing import Any

from taskloop.contracts import log as rec
from taskloop_dash.cache import FileCache
from taskloop_dash.views import detail
from taskloop_dash.views import timeline as tlv


class RunLogs:
    def __init__(self, files: FileCache) -> None:
        self.files = files

    def read(self, path: str) -> list[Any]:
        return tlv.read(path, self.files)

    def run_timeline(self, path: str, alive: bool = False, now: float | None = None) -> dict[str, Any]:
        return tlv.run_timeline(path, alive=alive, now=now, cache=self.files)

    def last_node(self, path: str) -> Any:
        return tlv.last_node(path, self.files)

    def block_detail(self, path: str, node_id: str | int, k: int = 0) -> dict[str, Any]:
        return detail.block_detail(path, node_id, k, self.files)

    @staticmethod
    def run_facts(recs: list[Any]) -> tuple[dict[str, str] | None, bool]:
        """(the run's start as {worktree, slot} or None, whether a close record is among the last 40)."""
        start = next((r for r in recs if isinstance(r, rec.RunStart)), None)
        return ({"worktree": start.worktree, "slot": start.slot or ""} if start else None), any(
            isinstance(r, rec.Close) for r in recs[-40:]
        )
