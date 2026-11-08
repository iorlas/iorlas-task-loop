"""Bind the dashboard launch rules to the installed shell paths and the machine's Tailscale address."""
import os
import shutil
from collections.abc import Mapping

from tlkernel.env import Env
from tlkernel.paths import default_root
from tlkernel.procport import Spawner

from taskloop.adapters.ident import PLUGIN_ROOT, config_dir
from tldash.cli import dash
from tldash.cli.dash import url

__all__ = ["run", "url"]


def tailscale_ip(spawn: Spawner) -> str | None:
    """Bind address discovery to this machine's executable and process port, at call time."""
    app = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    exe = shutil.which("tailscale") or (app if os.path.exists(app) else None)

    def ask(argv: list[str]) -> tuple[int, str]:
        r = spawn.run(argv, timeout_s=3.0)
        return r.exit, r.out

    return dash.tailscale_ip(exe, ask)


def run(op: str, env: Env, spawner: Spawner, installed: Mapping[str, int]) -> int:
    home = default_root(env) if op in ("status", "stop", "url") else config_dir(env)
    return dash.launch(op, env, spawner, lambda: tailscale_ip(spawner), installed, PLUGIN_ROOT, home)
