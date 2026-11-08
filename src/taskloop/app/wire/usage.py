"""`tl usage '<plan.windows JSON>'`: feed the Claude plan's usage windows to delegate, so headless Claude steps may run."""

from tlkernel.env import Env
from tlkernel.paths import ConfigDir
from tlkernel.procport import Spawner

from taskloop.adapters.ident import config_dir
from taskloop.app.doctor import accounts
from taskloop.stores.delegate import real_route


def feed(windows: str, spawner: Spawner, env: Env) -> int:
    return accounts.feed(windows, real_route(), lambda: ConfigDir(config_dir(env)))
