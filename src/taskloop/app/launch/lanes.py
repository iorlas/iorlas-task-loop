"""Bind the lane commands to the process route and config directory."""
from tlkernel.env import Env
from tlkernel.paths import ConfigDir

from taskloop.adapters.ident import config_dir
from taskloop.app.doctor import lanes
from taskloop.stores.delegate import real_route


def refresh(env: Env) -> int:
    return lanes.refresh(real_route(), ConfigDir(config_dir(env)))


def accounts(op: str, lane: str, env: Env) -> int:
    return lanes.accounts(op, lane, real_route(), ConfigDir(config_dir(env)))
