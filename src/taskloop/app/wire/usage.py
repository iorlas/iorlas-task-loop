"""`tl usage '<plan.windows JSON>'`: feed the Claude plan's usage windows to delegate, so headless Claude steps may run."""
import json

from taskloop.adapters import delegate as dg
from taskloop.adapters.ident import config_dir
from taskloop.app.wire import lanes
from taskloop.contracts.env import Env
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Spawner


def feed(windows: str, spawner: Spawner, env: Env) -> int:
    try:
        reading = json.loads(windows)
    except ValueError as e:
        print(f"the usage windows are no JSON: {e}")
        return 1
    try:
        snap = dg.status_snapshot(reading)
    except ValueError:
        print("delegate did not take the reading")
        return 1
    lanes.file_snapshot(snap, ConfigDir(config_dir(env)))  # the dashboard's lane cards read this
    lane = next((x for x in snap.lanes if x.id == "CLAUDE_SUBSCRIPTION"), None)
    if lane is None:
        print("delegate did not take the reading")
        return 1
    print("fed {}: Claude subscription 5h {}%, week {}%{}".format(dg.LIBRARY, lane.five, lane.week, ", OUT" if lane.out else ""))
    return 0
