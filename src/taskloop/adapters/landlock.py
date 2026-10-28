"""The repo's land lock (one per origin URL; every land and a release's push take it) and `tl land-lock`: a command run while holding it."""
import contextlib
import hashlib
import os
import signal
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from subprocess import Popen
from types import FrameType

from taskloop.adapters import locks, procs
from taskloop.adapters.gitrepo import git
from taskloop.adapters.ident import config_dir
from taskloop.contracts.locks import LockRecord, LockTimeout


@contextlib.contextmanager
def os_lock(path: Path | str, holder: str, waiting: Callable[[str], None] | None = None,
            timeout: float | None = None) -> Iterator[Path | str]:
    """One holder at a time, across processes (the vendored ProcessLock; the OS drops it when the process dies); a second taker waits.
    `waiting(text)` is called with the holder's name once, before blocking. With `timeout` (seconds) a wait that long raises TimeoutError
    (the holder's name in it)."""
    def told(rec: LockRecord | None) -> None:
        if waiting:
            waiting(rec.holder if rec else "?")
    try:
        with locks.hold_path(path, holder, timeout=timeout, waiting=told if waiting else None):
            yield path
    except LockTimeout as e:
        raise TimeoutError(e.holder.holder if e.holder else "?") from None


def land_lock_path(url: str) -> Path:
    """The repo's land lock (one per origin URL): every land, and a release's push, take it (os_lock)."""
    return config_dir() / "locks" / (f"land-{hashlib.sha1(url.encode()).hexdigest()[:12]}.lock")


def run_locked(cmd: list[str], repo: str, wait_min: float | None) -> int:
    """Run `cmd` while holding the land lock of `repo`; its exit code, 127 when it cannot start, 75 after `wait_min` minutes of waiting."""
    path = land_lock_path(git("remote", "get-url", "origin", cwd=repo) or repo)
    holder = f"land-lock pid {os.getpid()} ({' '.join(cmd)[:80]})"
    secs = wait_min * 60 if wait_min is not None else None
    child: list[Popen[bytes]] = []
    got: list[int] = []

    def stop(sig: int, _frame: FrameType | None) -> None:
        got.append(sig)
        for c in child:
            if c.poll() is None:
                procs.stop_tree(c)  # the child's tree, through stream-proc
        if not child:
            raise SystemExit(128 + sig)

    old = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        with os_lock(path, holder, lambda who: print(f"waiting for the land lock (held by {who})", flush=True), secs):
            try:
                p, hold = procs.popen_held(cmd)
            except OSError as e:
                print(f"land-lock: cannot run {cmd[0]}: {e}", file=sys.stderr)
                return 127
            child.append(p)
            hold.replay()
            rc = p.wait()
            return 128 + got[0] if got and rc < 0 else rc
    except TimeoutError as e:
        print(f"land-lock: gave up after {wait_min} min waiting for the land lock (held by {e})", file=sys.stderr)
        return 75
    finally:
        for s, h in old.items():
            signal.signal(s, h)
