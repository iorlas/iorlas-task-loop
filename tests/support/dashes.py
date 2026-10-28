"""A Dash over a temp state dir for a test: `make_dash(config=...)` reads XDG_CONFIG_HOME when no config is given, so make it after
the environment is patched. Its bd is the engine's adapter over whatever `bd` is on PATH (the launcher wires the same)."""
import shutil

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from taskloop.adapters.bd import BdStore
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports


def adapter_store(repo):
    if not shutil.which("bd"):
        raise OSError(2, "bd is not installed")
    return BdStore("tl-dash", repo or None)


def make_dash(ports=None, **kw):
    return Dash(Env(ports=ports or Ports(store=adapter_store), **kw))


__all__ = ["Dash", "Env", "Ports", "adapter_store", "make_dash"]
