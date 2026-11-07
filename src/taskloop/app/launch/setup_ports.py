"""Bind the setup verbs to the process route, the profile facts and the config dir's host store."""
from tlkernel.env import Env
from tlkernel.paths import ConfigDir
from tlslots import profile_facts

from taskloop.adapters.ident import config_dir
from taskloop.app.doctor.setup import ProfileFacts
from taskloop.app.doctor.setup_apply import HostStore
from taskloop.stores.delegate import real_route
from taskloop.stores.real import real_stores

facts: ProfileFacts = profile_facts
route = real_route


def host_store(env: Env) -> HostStore:
    return real_stores(ConfigDir(config_dir(env))).host
