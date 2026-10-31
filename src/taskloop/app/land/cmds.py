"""Every external command of a stack delivery: one argv, run through the Spawner, with a start row and an end row (run id, text, exit,
the tail of its output) in the run's log. A command that fails stops the delivery with its own exit code."""
from collections.abc import Callable, Mapping
from typing import Protocol, TypeVar

from taskloop.contracts import log as rec
from taskloop.contracts.argv import text_of
from taskloop.contracts.ports import Ran
from taskloop.contracts.slots import SlotGitError
from taskloop.stores.runlog import RunLog

T = TypeVar("T")
NOT_FOUND = 127  # the program is not there
TAIL = 600


class Runs(Protocol):
    """What a delivery reads of the Spawner: run an argv to its end."""

    def run(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None, extra: Mapping[str, str] | None = None,
            timeout_s: float | None = None, capture: bool = True) -> Ran: ...


class Stop(Exception):
    """The delivery ends here with `rc`: the exit code of the command that failed, 1 for a check of ours."""

    def __init__(self, rc: int, why: str) -> None:
        super().__init__(why)
        self.rc, self.why = rc, why


class Cmds:
    def __init__(self, spawner: Runs, log: RunLog, cwd: str) -> None:
        self.spawner, self.log, self.cwd = spawner, log, cwd

    def port(self, text: str, fn: Callable[[], T]) -> T:
        """A call of the Git port as a command row; git's refusal ends the delivery (the port keeps git's words, not its exit code: 1)."""
        cid = self.log.next_id("c")
        self.log.emit(rec.CmdStart(id=cid, text=text, cwd=self.cwd))
        try:
            got = fn()
        except SlotGitError as e:
            self.log.emit(rec.CmdEnd(id=cid, exit=1, out=e.tail[-TAIL:]))
            raise Stop(1, f"{text} failed: {e.tail.strip()[-300:]}") from None
        self.log.emit(rec.CmdEnd(id=cid, exit=0))
        return got

    def row(self, text: str, fn: Callable[[], object]) -> int:
        """A step of ours that is no process (a branch delete through the Git port) as a command row; -> its exit (0, or 1 with the port's
        words in the row)."""
        cid = self.log.next_id("c")
        self.log.emit(rec.CmdStart(id=cid, text=text, cwd=self.cwd))
        try:
            fn()
            code, out = 0, ""
        except Exception as e:  # the port's own refusal (a ref that moved, a worktree that stays): the row says why
            code, out = 1, str(e)[-TAIL:]
        self.log.emit(rec.CmdEnd(id=cid, exit=code, out=out))
        return code

    def run(self, argv: list[str]) -> Ran:
        """Run `argv` in the repo; the rows are written whatever it does. A program that is not there is exit 127."""
        cid = self.log.next_id("c")
        self.log.emit(rec.CmdStart(id=cid, text=text_of(argv), cwd=self.cwd))
        try:
            ran = self.spawner.run(argv, cwd=self.cwd)
        except OSError as e:
            ran = Ran(exit=NOT_FOUND, err=str(e))
        self.log.emit(rec.CmdEnd(id=cid, exit=ran.exit, out=(ran.out + ran.err)[-TAIL:]))
        return ran

    def must(self, argv: list[str]) -> Ran:
        ran = self.run(argv)
        if ran.exit != 0:
            raise Stop(ran.exit, f"{text_of(argv)} failed (exit {ran.exit}): {(ran.err or ran.out).strip()[-300:]}")
        return ran
