"""Bind the account commands to the process route and config directory."""
from tlkernel.env import Env
from tlkernel.paths import ConfigDir

from taskloop.adapters.ident import config_dir
from taskloop.app.doctor import accounts as doctor_accounts
from taskloop.stores.delegate import real_route


def refresh(env: Env) -> int:
    return doctor_accounts.refresh(real_route(), ConfigDir(config_dir(env)))


def accounts(op: str, account: str, env: Env) -> int:
    return doctor_accounts.accounts(op, account, real_route(), ConfigDir(config_dir(env)))
