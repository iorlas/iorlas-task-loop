"""The factory launcher's binding: the machine facts (plugin version, the platform keep-awake) the loop node's loops are given."""
from taskloop.adapters import factory as platform_factory
from taskloop.adapters.ident import plugin_version

caffeinate_argv = platform_factory.caffeinate_argv


def version() -> str:
    return plugin_version() or "unknown"
