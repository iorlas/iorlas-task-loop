"""Where a check runs (on the host) and the environment its receipt is keyed by."""
from taskloop.adapters import childenv
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.runkey import Digest

HOST_IDENTITY = Digest("host-v1")  # every check runs on this machine: the execution field of its run key


def check_env() -> dict[str, str]:
    """The admitted environment shared by standalone checks and delivery queries."""
    return {EnvVar.TL_SLOT.value: "check"}


def keyed_env(env: Env) -> dict[str, str]:
    """The shared receipt environment, independent of the executing slot's name and state paths."""
    return {**childenv.reaching(childenv.current_env(env)), **check_env()}
