"""Is a running check doing anything? The CPU of its process tree and the files written under the worktree."""
import os
from collections.abc import MutableMapping
from typing import Any

from taskloop.adapters import procs


def tree_cpu(root_pid: int) -> dict[int, float] | None:
    """{pid: cpu seconds} for the process tree under root_pid and every member of its group; None where the system lists no
    processes at all (macOS has no /proc): the CPU is then unknown, which is not the same as idle."""
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
        return True  # no process table: cannot tell, so never call it hung; the check's wall-time cap is the only guard there
    if prev_sig is None or sig != prev_sig:
        return True
    return any(k not in prev_cpu or v > prev_cpu[k] for k, v in cpu.items())
