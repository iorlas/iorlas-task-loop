"""CheckLog: the records of the checks of a round. Every check leaves a start and an end under one id (one that never ran, a
cached or reused or skipped result, leaves both at once), and the round leaves one Checks record: the CheckRun."""
from taskloop.contracts.checks import Check, CheckResult, CheckRun
from taskloop.contracts.log import CheckEnd, Checks, CheckStart
from taskloop.stores.runlog import RunLog


class CheckLog:
    def __init__(self, log: RunLog) -> None:
        self.log = log

    def start(self, c: Check, rnd: int, log: str = "") -> str:
        """A check begins running: its id, which `close` ends."""
        cid = self.log.next_id("k")
        self.log.emit(CheckStart(id=cid, check=c.id, group=c.group, cmd=c.cmd, round=rnd, log=log, timeout_s=c.wall_min * 60,
                               lane=c.lane))
        return cid

    def close(self, c: Check, res: CheckResult, cid: str | None, rnd: int) -> None:
        """The check's result; `cid` None: it did not run (skipped, cached, reused), so its start is written now."""
        cid = cid or self.start(c, rnd, res.log)
        self.log.emit(CheckEnd(id=cid, exit=res.exit, status=res.word, tries=res.tries, exec_seconds=res.secs, wall_hit=res.wall_hit,
                               wait_seconds=res.waited, lane=c.lane, at=res.at, cancelled=res.cancelled))

    def round(self, node_id: str, run: CheckRun) -> None:
        self.log.emit(Checks(node_id=node_id, run=run))
