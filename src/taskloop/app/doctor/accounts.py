"""Account commands and the loop snapshot chore: ask delegate for its status once (`delegate.api.status`, spends no quota).
File it as the StatusSnapshot the
dashboard reads, and each window's use into the usage history. `tl usage` files it too, on its way. The dashboard never runs delegate."""
import json
import time
from collections.abc import Callable

from tlkernel import paths
from tlkernel.delegateport import Route
from tlkernel.rowstores import StatusStore, StatusTriedStore
from tlkernel.snapshots import StatusSnapshot, StatusTried
from tlkernel.stores import UsageHistory

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


def file_status(route: Route, cfg: paths.ConfigDir) -> str | None:
    """Ask delegate and file the answer. None when filed, else a line saying why not."""
    try:
        snap = route.status_snapshot()
    except ValueError as e:
        return f"delegate status not filed: {e}"
    return file_snapshot(snap, cfg)


def refresh(route: Route, cfg: paths.ConfigDir) -> int:
    why = file_status(route, cfg)
    print(why or f"filed delegate status at {time.strftime('%H:%M:%S')}")
    return 1 if why else 0


def due(cfg: paths.ConfigDir, now: float, every: float = EVERY_S) -> bool:
    """Neither a filed snapshot nor an attempt (a failed one leaves a marker) is newer than `every` seconds."""
    snap = StatusStore(cfg).get()
    mark = StatusTriedStore(cfg).get()
    tried = mark.t if mark else 0.0
    return now - max(snap.at if snap else 0.0, tried) >= every


def chore(say: Callable[[str], None], route: Route, cfg: paths.ConfigDir, now: float | None = None) -> bool:
    """The loop's `chores` step: file delegate's status again when the snapshot is `EVERY_S` old. -> whether it asked."""
    when = time.time() if now is None else now
    if not due(cfg, when):
        return False
    StatusTriedStore(cfg).write(StatusTried(t=when))
    why = file_status(route, cfg)
    if why:
        say(f"loop: {why}")
    return True


def accounts(op: str, account: str, route: Route, cfg: paths.ConfigDir) -> int:
    """`tl accounts [enable|decline ACCOUNT]`: the worker accounts delegate can use, what each needs, and the owner's choice for one."""
    try:
        if op in ("enable", "decline"):
            if not account:
                print(f"usage: tl accounts {op} ACCOUNT")
                return 2
            route.set_account(account, op == "enable")
            print(f"{account}: {'enabled' if op == 'enable' else 'declined'}")
        rows = route.accounts()
    except (ValueError, SystemExit, OSError) as e:
        print(f"accounts: {e}")
        return 1
    width = max((len(r.account) for r in rows), default=4)
    print(f"{'account':<{width}}  enabled  ready  fix")
    for r in rows:
        print(f"{r.account:<{width}}  {'yes' if r.enabled else 'no':<7}  {'yes' if r.ready else 'no':<5}  {r.fix}".rstrip())
    return 0


def feed(windows: str, route: Route, cfg: Callable[[], paths.ConfigDir]) -> int:
    """Validate and file a usage reading, then report its Claude account."""
    try:
        reading = json.loads(windows)
    except ValueError as e:
        print(f"the usage windows are no JSON: {e}")
        return 1
    try:
        snap = route.status_snapshot(reading)
    except ValueError:
        print("delegate did not take the reading")
        return 1
    file_snapshot(snap, cfg())  # the dashboard's account cards read this
    account = next((x for x in snap.accounts if x.id == "CLAUDE_SUBSCRIPTION"), None)
    if account is None:
        print("delegate did not take the reading")
        return 1
    print("fed {}: Claude subscription 5h {}%, week {}%{}".format(
        route.library, account.five, account.week, ", OUT" if account.out else ""))
    return 0
