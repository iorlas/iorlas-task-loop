"""Lane status for dash tests: a delegate status answer filed as the StatusSnapshot the dash reads, and lanes built from dicts."""
import time
from typing import Any

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from tlkernel.delegate_status import snapshot_of
from tlkernel.rowstores import StatusStore


def lane(**kw: Any) -> dict[str, Any]:
    return dict({"family": "claude", "kind": "subscription", "out": False, "out_until": None, "notes": []}, **kw)


def answer(lanes: dict[str, Any], **top: Any) -> dict[str, Any]:
    """A typed status answer for these top-level lanes, with one cockpit row each."""
    rows = [{"id": n, "state": "resting" if ln.get("out") else "ready", "model": ln.get("model"),
             "family": ln.get("family"), "kind": ln.get("kind")} for n, ln in lanes.items()]
    return dict({"v": 1, "ts": time.time(), "accounts": lanes, "cockpit": {"v": 1, "accounts": rows}}, **top)


def file_status(dash: Any, j: dict[str, Any]) -> None:
    StatusStore(dash.env.config).write(snapshot_of(j))
