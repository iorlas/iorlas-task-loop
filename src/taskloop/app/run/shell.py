"""A command of the run: an argv list run by stream-proc in a group of its own, recorded in the engine log."""
import time
from pathlib import Path
from typing import Any

import outcome as oc
import stream_proc

from taskloop.adapters import procs as sproc
from taskloop.adapters.gitenv import pinned_env
from taskloop.app.run.blocked import Blocked
from taskloop.contracts import log as rec
from taskloop.contracts.argv import text_of


class Shell:
    def __init__(self, host: Any) -> None:
        self.e = host

    def run(self, cmd: Any, timeout: float = 3600, check: bool = False, save: Any = None, env: Any = None, pin: bool = False,
            what: str = "command", cwd: Any = None) -> tuple[int, str]:
        """A command: an argv list, exec'd as given (no shell, no quoting rules; a string is a programming error), run by stream-proc
        in a group of its own. It ends by itself, at `timeout` seconds of wall time (exit 124; its tree is stopped), or when
        the run's halt is set. Nothing else stops it: a quiet command may be waiting. pin=True: an engine git command, run with
        GIT_DIR/GIT_WORK_TREE of the slot; checks and gates run unpinned (they may run git on other repos)."""
        e = self.e
        if isinstance(cmd, str):
            raise TypeError(f"a command is an argv list, never a string: {cmd[:80]!r}")
        if what == "check" and e.halt.is_set():  # a stop: no check starts; it reports itself failed, the run stops at its next safe point
            e.killed = True
            return -15, ""
        cid = e.log.next_id("m")
        cwd = cwd or e.wt  # a check on the untouched base runs in its own checkout
        e.log.emit(rec.CmdStart(id=cid, text=text_of(cmd), cwd=str(cwd)))
        started = time.time()
        chunks: list[str] = []
        e.killed = e.wall_hit = False
        res = self.stream(cmd, cwd, env, pin, chunks, timeout, cid, what, started)
        rc = 124 if res.timed_out == "wall" else -res.signal if res.signal else res.returncode or 0
        text = "".join(chunks)
        if res.timed_out:  # only a stop the engine performed; a command that exits 124 by itself is not a kill
            text += self.killed(res, rc, what, timeout, started)
        if save:
            Path(save).write_text(text, encoding="utf-8")
        tail = "\n".join(text.strip().splitlines()[-15:])
        e.log.emit(rec.CmdEnd(id=cid, exit=rc, secs=round(time.time() - started, 1), out=tail[-600:] if rc else ""))
        e.halt_point(what != "check")  # a stop, not the command's verdict (a stopped check reports itself first)
        if check and rc:
            raise Blocked(f"failed: `{text_of(cmd)}` exit {rc}\n{tail}", kind=oc.Kind.FAULT_INFRA)
        return rc, tail

    def stream(self, cmd: Any, cwd: Any, env: Any, pin: bool, chunks: list[str], timeout: float, cid: str, what: str,
               started: float) -> Any:
        e = self.e
        full_env = dict(sproc.current_env(), **(pinned_env(e.wt) if pin else {}), **(env or {}))
        try:
            return stream_proc.run(list(cmd), cwd=cwd, env=full_env, on_stdout=chunks.append, on_stderr=chunks.append, timeout=timeout,
                                   stop=e.halt)
        except BaseException:  # stopped (stream-proc stopped the tree first): never leave a check (just check, Unity) running
            now = time.time()
            e.killed = True
            e.log.emit(rec.Kill(what=what, why="interrupted", secs=round(now - started), started_t=started, kill_t=now, observed_t=now))
            e.log.emit(rec.CmdEnd(id=cid, exit=-1, secs=round(now - started, 1)))
            raise

    def killed(self, res: Any, rc: int, what: str, timeout: float, started: float) -> str:
        """The engine stopped the command (its wall limit, or a stop): recorded; the words added to its output."""
        e = self.e
        now = time.time()
        e.killed, e.wall_hit = True, res.timed_out == "wall"
        e.log.emit(rec.Kill(what=what, why="timeout" if e.wall_hit else res.timed_out, secs=round(res.secs), exit=rc,
                            started_t=started, kill_t=now, observed_t=now, alive=list(res.survivors)))
        if e.wall_hit:
            return f"\n(timed out after {round(timeout / 60, 2):g} min: the engine stopped it and everything it started)"
        return ""
