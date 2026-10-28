"""What a running check is doing: the CPU of its process tree and the files written under the worktree. Looked at, never judged:
a quiet check may be waiting (asleep, on a lock, on the network, Unity importing), so only its wall limit stops it."""
import os
import time
from collections.abc import Callable, MutableMapping
from typing import Any

from taskloop.adapters import procs
from taskloop.contracts.log import ActivitySample

ACTIVITY_EVERY = 30.0  # seconds between two samples of one check in the log


def tree_cpu(root_pid: int) -> dict[int, float] | None:
    """{pid: cpu seconds} for the process tree under root_pid and every member of its group; None where the system lists no
    processes at all (no readable process table): the CPU is then unknown, which is not the same as idle."""
    table = procs.table()
    if table is None:
        return None
    rows = {p.pid: p for p in table.values()}
    mine, todo = {root_pid}, [root_pid]
    while todo:
        cur = todo.pop()
        for k, p in rows.items():
            if p.ppid == cur and k not in mine:
                mine.add(k)
                todo.append(k)
    mine |= {k for k, p in rows.items() if p.pgid == root_pid}
    return {k: rows[k].cpu_s for k in mine if k in rows}


def files_signature(wt: str) -> tuple[int, int, int]:
    """(files, bytes, newest mtime) under the worktree, .git left out."""
    n = size = newest = 0
    for dp, dns, fns in os.walk(wt):
        dns[:] = [d for d in dns if d != ".git"]
        for f in fns:
            try:
                st = os.lstat(os.path.join(dp, f))
            except OSError:
                continue
            n += 1
            size += st.st_size
            newest = max(newest, st.st_mtime_ns)
    return (n, size, newest)


def activity(wt: str, root_pid: int, seen: MutableMapping[str, Any]) -> bool:
    """True when since the last call the tree under root_pid used CPU (or started a process) or a file under `wt` changed
    (a count, a size or an mtime). `seen` carries the last look; the first call only takes it (and counts as activity)."""
    cpu, sig = tree_cpu(root_pid), files_signature(wt)
    prev_cpu, prev_sig = seen.get("cpu") or {}, seen.get("files")
    seen["cpu"], seen["files"] = cpu, sig
    if cpu is None:
        return True  # no process table: cannot tell, the wall limit is the only guard
    if prev_sig is None or sig != prev_sig:
        return True
    return any(k not in prev_cpu or v > prev_cpu[k] for k, v in cpu.items())


class Sampler:
    """The look at one running check, at most one ActivitySample per `every` seconds."""

    def __init__(self, wt: str, root_pid: int, cmd_id: str, started: float, every: float | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.wt, self.pid, self.cmd_id, self.started, self.every, self.clock = wt, root_pid, cmd_id, started, every or ACTIVITY_EVERY, clock
        self.seen: dict[str, Any] = {"files": None, "cpu": {}}
        self.next_t, self.moved_t = started, started

    def take(self, out_bytes: int, last_output_t: float) -> ActivitySample | None:
        """A sample when one is due, else None. `moved_t` (read after) is the last time anything was seen moving."""
        now = self.clock()
        if now < self.next_t:
            return None
        if activity(self.wt, self.pid, self.seen):
            self.moved_t = self.clock()
        self.next_t = now + self.every
        cpu, files = self.seen["cpu"], self.seen["files"]
        return ActivitySample(cmd_id=self.cmd_id, secs=round(now - self.started, 1), out_bytes=out_bytes,
                              silent_s=round(now - max(self.moved_t, last_output_t), 1), pids=sorted(cpu or {}),
                              cpu_s=None if cpu is None else round(sum(cpu.values()), 2), files=files[0], file_bytes=files[1],
                              newest_mtime_ns=files[2])
