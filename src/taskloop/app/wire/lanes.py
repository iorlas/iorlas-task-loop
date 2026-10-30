"""`tl lanes`: ask delegate for its status once (`route.py status --json`, spends no quota) and file it as the StatusSnapshot the
dashboard reads, and each window's use into the usage history. `tl usage` files it too, on its way. The dashboard never runs delegate."""
import json
import sys
import time
from collections.abc import Callable

from taskloop.adapters import delegate as sdelegate
from taskloop.adapters.ident import claude_dir
from taskloop.app.release.pins import pinned_dir
from taskloop.contracts import paths
from taskloop.contracts.delegate_status import snapshot_of
from taskloop.contracts.ports import Spawner
from taskloop.contracts.snapshots import StatusTried
from taskloop.contracts.stores import StatusStore, StatusTriedStore, UsageHistory

EVERY_S = 20 * 60  # the loop files delegate's status again when the snapshot is this old


def find() -> str | None:
    return sdelegate.find_route("", pinned_dir("delegate"), claude_dir() / "plugins" / "cache", sdelegate.installed_dir(claude_dir()))


def file_answer(text: str) -> str | None:
    """Parse one `status --json` answer and file it. None when filed, else why not."""
    try:
        snap = snapshot_of(json.loads(text[text.index("{"):]))
        cfg = paths.ConfigDir()
        StatusStore(cfg).write(snap)
        history = UsageHistory(cfg)  # the usage history grows with each filed snapshot and is pruned by age here, its one owner
        history.record(snap)
        history.prune(snap.at)
    except (ValueError, OSError) as e:
        return f"delegate status not filed: {e}"
    return None


def file_status(spawner: Spawner) -> str | None:
    """Ask delegate and file the answer. None when filed, else a line saying why not (no delegate is not a failure: None)."""
    route = find()
    if not route:
        return None
    r = spawner.run([sys.executable, route, "status", "--json"], timeout_s=60.0)
    return file_answer(r.out) if r.exit == 0 else f"delegate status exited {r.exit}: {(r.err or r.out)[-200:]}"


def refresh(spawner: Spawner) -> int:
    if not find():
        print("no delegate installed: nothing to file")
        return 0
    why = file_status(spawner)
    print(why or f"filed delegate status at {time.strftime('%H:%M:%S')}")
    return 1 if why else 0


def due(cfg: paths.ConfigDir, now: float, every: float = EVERY_S) -> bool:
    """Neither a filed snapshot nor an attempt (a failed one leaves a marker) is newer than `every` seconds."""
    snap = StatusStore(cfg).read()
    mark = StatusTriedStore(cfg).read()
    tried = mark.t if mark else 0.0
    return now - max(snap.at if snap else 0.0, tried) >= every


def chore(say: Callable[[str], None], spawner: Spawner, cfg: paths.ConfigDir | None = None, now: float | None = None) -> bool:
    """The loop's `chores` step: file delegate's status again when the snapshot is `EVERY_S` old. -> whether it asked."""
    cfg = cfg or paths.ConfigDir()
    when = time.time() if now is None else now
    if not due(cfg, when):
        return False
    StatusTriedStore(cfg).write(StatusTried(t=when))
    why = file_status(spawner)
    if why:
        say(f"loop: {why}")
    return True
