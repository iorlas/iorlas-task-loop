"""`tl lanes`: ask delegate for its status once (`route.py status --json`, spends no quota) and file it as the StatusSnapshot the
dashboard reads. `tl usage` files it too, on its way. The dashboard never runs delegate."""
import json
import sys
import time

from taskloop.adapters import delegate as sdelegate
from taskloop.adapters import procs
from taskloop.adapters.ident import claude_dir
from taskloop.app.release.pins import pinned_dir
from taskloop.contracts import paths
from taskloop.contracts.delegate_status import snapshot_of
from taskloop.contracts.stores import StatusStore


def find() -> str | None:
    return sdelegate.find_route("", pinned_dir("delegate"), claude_dir() / "plugins" / "cache", sdelegate.installed_dir(claude_dir()))


def file_answer(text: str) -> str | None:
    """Parse one `status --json` answer and file it. None when filed, else why not."""
    try:
        StatusStore(paths.ConfigDir()).write(snapshot_of(json.loads(text[text.index("{"):])))
    except (ValueError, OSError) as e:
        return f"delegate status not filed: {e}"
    return None


def refresh() -> int:
    route = find()
    if not route:
        print("no delegate installed: nothing to file")
        return 0
    r = procs.capture([sys.executable, route, "status", "--json"], None, None, 60.0)
    why = file_answer(r.out) if r.exit == 0 else f"delegate status exited {r.exit}: {(r.err or r.out)[-200:]}"
    print(why or f"filed delegate status at {time.strftime('%H:%M:%S')}")
    return 1 if why else 0
