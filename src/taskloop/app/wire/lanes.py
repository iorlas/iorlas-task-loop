"""`tl lanes`: ask delegate for its status once (`route.py status --json`, spends no quota) and file it as the StatusSnapshot the
dashboard reads, and each window's use into the usage history. `tl usage` files it too, on its way. The dashboard never runs delegate."""
import time
from collections.abc import Callable

from taskloop.adapters import delegate as sdelegate
from taskloop.adapters.ident import config_dir
from taskloop.contracts import paths
from taskloop.contracts.env import Env
from taskloop.contracts.ports import Spawner
from taskloop.contracts.snapshots import StatusSnapshot, StatusTried
from taskloop.contracts.stores import StatusStore, StatusTriedStore, UsageHistory

EVERY_S = 20 * 60  # the loop files delegate's status again when the snapshot is this old


def file_snapshot(snap: StatusSnapshot, cfg: paths.ConfigDir) -> str | None:
    """File one status snapshot and its usage history. None when filed, else why not."""
    try:
        StatusStore(cfg).write(snap)
        history = UsageHistory(cfg)  # the usage history grows with each filed snapshot and is pruned by age here, its one owner
        history.record(snap)
        history.prune(snap.at)
    except (ValueError, OSError) as e:
        return f"delegate status not filed: {e}"
    return None


def file_status(spawner: Spawner, env: Env) -> str | None:
    """Ask delegate and file the answer. None when filed, else a line saying why not."""
    try:
        snap = sdelegate.status_snapshot()
    except ValueError as e:
        return f"delegate status not filed: {e}"
    return file_snapshot(snap, paths.ConfigDir(config_dir(env)))


def refresh(spawner: Spawner, env: Env) -> int:
    why = file_status(spawner, env)
    print(why or f"filed delegate status at {time.strftime('%H:%M:%S')}")
    return 1 if why else 0


def due(cfg: paths.ConfigDir, now: float, every: float = EVERY_S) -> bool:
    """Neither a filed snapshot nor an attempt (a failed one leaves a marker) is newer than `every` seconds."""
    snap = StatusStore(cfg).get()
    mark = StatusTriedStore(cfg).get()
    tried = mark.t if mark else 0.0
    return now - max(snap.at if snap else 0.0, tried) >= every


def chore(say: Callable[[str], None], spawner: Spawner, env: Env, now: float | None = None) -> bool:
    """The loop's `chores` step: file delegate's status again when the snapshot is `EVERY_S` old. -> whether it asked."""
    cfg = paths.ConfigDir(config_dir(env))
    when = time.time() if now is None else now
    if not due(cfg, when):
        return False
    StatusTriedStore(cfg).write(StatusTried(t=when))
    why = file_status(spawner, env)
    if why:
        say(f"loop: {why}")
    return True


def accounts(op: str, lane: str) -> int:
    """`tl accounts [enable|decline LANE]`: the worker accounts delegate can use, what each needs, and the owner's choice for one."""
    try:
        if op in ("enable", "decline"):
            if not lane:
                print(f"usage: tl accounts {op} LANE")
                return 2
            sdelegate.set_account(lane, op == "enable")
            print(f"{lane}: {'enabled' if op == 'enable' else 'declined'}")
        rows = sdelegate.accounts()
    except (ValueError, SystemExit, OSError) as e:
        print(f"accounts: {e}")
        return 1
    width = max((len(r.lane) for r in rows), default=4)
    print(f"{'lane':<{width}}  enabled  ready  fix")
    for r in rows:
        print(f"{r.lane:<{width}}  {'yes' if r.enabled else 'no':<7}  {'yes' if r.ready else 'no':<5}  {r.fix}".rstrip())
    return 0
