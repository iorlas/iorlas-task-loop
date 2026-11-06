"""`tl usage '<plan.windows JSON>'`: feed the Claude plan's usage windows to delegate, so headless Claude steps may run."""
import json

from taskloop.adapters import delegate as dg
from taskloop.adapters.ident import config_dir
from taskloop.app.wire import lanes
from taskloop.contracts.env import Env
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.procport import Spawner


def feed(windows: str, spawner: Spawner, env: Env) -> int:
    try:
        reading = json.loads(windows)
    except ValueError as e:
        print(f"the usage windows are no JSON: {e}")
        return 1
    status = dg.status_json(reading)
    lanes.file_answer(json.dumps(status), ConfigDir(config_dir(env)))  # the dashboard's lane cards read this
    try:
        lane = status["lanes"]["CLAUDE_SUBSCRIPTION"]
        print("fed {}: Claude subscription 5h {}%, week {}%{}".format(dg.LIBRARY, lane.get("five"), lane.get("week"),
                                                                     ", OUT" if lane.get("out") else ""))
    except (KeyError, TypeError):
        print("delegate did not take the reading")
        return 1
    return 0
