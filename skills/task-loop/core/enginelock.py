"""The engine lock: <worktree>/.task/engine.lock while run-task runs there (see tl.engine_busy), and the workers it started.
O1 (slots, locks) replaces this with the Lease; until then it is the one writer of the file's `route` and `workers` lists."""
import contextlib
import os
import time

import stream_proc
import tl

class EngineLock:
    """<worktree>/.task/engine.lock while run-task runs there (see tl.engine_busy). A worker that outlived its stop keeps
    the lock (pid 0) until it is gone."""

    def __init__(self, wt, bead, slot=""):
        self.wt = wt
        self.path = tl.engine_lock_path(wt)
        self.data = {"pid": os.getpid(), "start": stream_proc.proc_start(os.getpid()), "bead": bead, "slot": slot or "",
                     "slot_bead": os.environ.get("TASK_LOOP_SLOT_BEAD", ""), "by": "run-task", "started": time.time(),
                     "route": None, "workers": []}

    def take(self):
        """"" when this run holds the worktree now, else what holds it. A run the loop started takes over the loop's
        lock for its slot."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handoff = True  # engine_busy lets it take over only its parent loop's lock for the same slot bead
        for _ in range(3):
            busy = tl.engine_busy(self.wt, handoff=handoff)
            if busy:
                return busy
            try:  # created only if absent: two runs starting at once cannot both win
                os.close(os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            except FileExistsError:
                with contextlib.suppress(OSError):  # a dead run's lock or the parent loop's (engine_busy said so)
                    if not tl.engine_busy(self.wt, handoff=handoff):
                        self.path.unlink()
                continue
            self.write()
            return ""
        return "another run took the engine lock at the same time"

    def write(self):
        tl.write_engine_lock(self.wt, self.data)

    def note(self, route_pid=False, **kw):
        if route_pid is not False:
            kw["route"] = [route_pid, stream_proc.proc_start(route_pid)] if route_pid else None
        self.data.update(kw)
        with contextlib.suppress(OSError):
            self.write()

    def release(self):
        left = [w for w in self.data.get("workers") or [] if stream_proc.alive(w[0], w[1])]
        with contextlib.suppress(OSError):
            if left:
                self.data.update(pid=0, route=None, workers=left)
                self.write()
            else:
                self.path.unlink()


LOCK = None  # this process's EngineLock while run-task runs
