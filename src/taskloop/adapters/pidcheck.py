"""Is a process alive, and the start token that tells it from a later one with the same pid (stream-proc)."""
from taskloop.adapters import procs


def proc_start(pid: object) -> str:
    """The process's start token as text, "" when unknown."""
    return (procs.proc_start(int(str(pid))) or "") if pid else ""


def proc_alive(pid: object, start: str = "") -> bool:
    """The process `pid` lives, is no zombie, and (when `start` is known) is the one that started then."""
    return bool(pid) and procs.alive(int(str(pid)), start or None)


def pid_alive(pid: object) -> bool:
    return bool(pid) and procs.alive(int(str(pid)))
