"""Bind the dashboard launch rules to the installed shell paths."""
from collections.abc import Mapping

from tlkernel.env import Env
from tlkernel.paths import default_root
from tlkernel.procport import Spawner

from taskloop.adapters.ident import PLUGIN_ROOT, config_dir
from tldash.cli import dash
from tldash.cli.dash import url

__all__ = ["run", "url"]


def run(op: str, env: Env, spawner: Spawner, installed: Mapping[str, int]) -> int:
    home = default_root(env) if op in ("status", "stop", "url") else config_dir(env)
    return dash.run(op, env, spawner, installed, PLUGIN_ROOT, home)
