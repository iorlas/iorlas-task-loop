"""CheckLog: the records of the checks of a round. Every check leaves a start and an end under one id (one that never ran, a
cached or reused or skipped result, leaves both at once), and the round leaves one Checks record with every result."""
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from taskloop.contracts.log import CheckEnd, CheckItem, Checks, CheckStart
from taskloop.stores.runlog import RunLog

STATUS = MappingProxyType({"ran": "passed", "failed": "failed", "skipped": "skipped"})


def status_of(res: Mapping[str, Any]) -> str:
    """The CheckStatus word of a result: cached, hung, timeout (exit 124), passed, failed or skipped."""
    if res.get("cached"):
        return "cached"
    if res.get("hung"):
        return "hung"
    return "timeout" if res.get("exit") == 124 else STATUS[res["status"]]


class CheckLog:
    def __init__(self, log: RunLog) -> None:
        self.log = log

    def start(self, c: Mapping[str, Any], rnd: int, log: str = "") -> str:
        """A check begins running: its id, which `close` ends."""
        cid = self.log.next_id("k")
        self.log.emit(CheckStart(id=cid, check=c["id"], group=c["group"], cmd=c["cmd"], round=rnd, log=log, timeout_s=float(c["timeout"]) * 60))
        return cid

    def close(self, c: Mapping[str, Any], res: Mapping[str, Any], cid: str | None, rnd: int) -> None:
        """The check's result; `cid` None: it did not run (skipped, cached, reused), so its start is written now."""
        cid = cid or self.start(c, rnd, "" if res.get("cached") or res.get("reused") else res.get("log") or "")
        self.log.emit(CheckEnd(id=cid, exit=res["exit"], status=status_of(res), tries=res.get("tries") or 1, secs=float(res.get("secs") or 0)))

    def round(self, node_id: str, rnd: int, out: list[dict[str, Any]], tree: str) -> None:
        hits = sum(1 for c in out if c.get("cached"))
        self.log.emit(Checks(node_id=node_id, round=rnd, tree=tree, hits=hits, misses=len(out) - hits, items=[
            CheckItem(id=c["id"], cmd=c["cmd"], group=c["group"], exit=c["exit"], status=c["status"], secs=c.get("secs"), tries=c.get("tries"),
                      hung=bool(c.get("hung")), cached=bool(c.get("cached")), reused=bool(c.get("reused")), why=c.get("why") or "",
                      log="" if c.get("cached") or c.get("reused") else c.get("log") or "") for c in out]))
