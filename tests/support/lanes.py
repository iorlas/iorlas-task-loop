"""Lane status for dash tests: a delegate status answer filed as the StatusSnapshot the dash reads, and lanes built from dicts."""
import time
from typing import Any

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from taskloop.contracts.delegate_status import snapshot_of
from taskloop.contracts.snapshots import LaneStatus
from taskloop.contracts.stores import StatusStore


def lane(**kw: Any) -> dict[str, Any]:
    return dict({"family": "claude", "kind": "subscription", "out": False, "out_until": None, "notes": []}, **kw)


def answer(lanes: dict[str, Any], **top: Any) -> dict[str, Any]:
    """A typed status answer for these top-level lanes, with one cockpit row each."""
    rows = [{"id": n, "state": "resting" if ln.get("out") else "ready", "model": ln.get("model"),
             "family": ln.get("family"), "kind": ln.get("kind")} for n, ln in lanes.items()]
    return dict({"v": 1, "ts": time.time(), "lanes": lanes, "cockpit": {"v": 1, "lanes": rows}}, **top)


def file_status(dash: Any, j: dict[str, Any]) -> None:
    StatusStore(dash.env.config).write(snapshot_of(j))


def lane_statuses(lanes: dict[str, Any]) -> list[LaneStatus]:
    return snapshot_of(answer(lanes)).lanes
