"""A Dash over a temp state dir for a test: `make_dash(config=...)` reads XDG_CONFIG_HOME when no config is given, so make it after
the environment is patched."""
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from taskloop_dash.app import Dash
from taskloop_dash.env import Env, Ports


def make_dash(**kw):
    return Dash(Env(**kw))


__all__ = ["Dash", "Env", "Ports", "make_dash"]
