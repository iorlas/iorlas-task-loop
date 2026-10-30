"""`tl usage '<plan.windows JSON>'`: feed the Claude plan's usage windows to delegate, so headless Claude steps may run."""
import json
import sys

from taskloop.adapters import delegate as sdelegate
from taskloop.adapters.ident import claude_dir
from taskloop.app.release.pins import pinned_dir
from taskloop.app.wire import lanes, real
from taskloop.contracts.ports import Spawner


def feed(windows: str, spawner: Spawner | None = None) -> int:
    route = sdelegate.find_route("", pinned_dir("delegate"), claude_dir() / "plugins" / "cache", sdelegate.installed_dir(claude_dir()))
    if not route:
        print("no delegate installed: nothing to feed")
        return 0
    r = (spawner or real.spawner()).run([sys.executable, route, "status", "--claude-usage", windows, "--json"], timeout_s=60.0)
    lanes.file_answer(r.out)  # the dashboard's lane cards read this
    try:
        lane = json.loads(r.out)["lanes"]["CLAUDE_SUBSCRIPTION"]
        print("fed {}: Claude subscription 5h {}%, week {}%{}".format(route, lane.get("five"), lane.get("week"),
                                                                     ", OUT" if lane.get("out") else ""))
    except (ValueError, KeyError, TypeError):
        print(f"delegate did not take the reading (exit {r.exit}): {(r.err or r.out)[-400:]}")
        return 1
    return 0
