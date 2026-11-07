"""Bind the dashboard launch rules to the installed shell paths and the machine's Tailscale address."""
import ipaddress
import os
import shutil
from collections.abc import Mapping

from tlkernel.env import Env
from tlkernel.paths import default_root
from tlkernel.procport import Spawner

from taskloop.adapters.ident import PLUGIN_ROOT, config_dir
from tldash import bind as dash_bind
from tldash.cli import dash
from tldash.cli.dash import url

__all__ = ["run", "url"]


def tailscale_ip(spawn: Spawner) -> str | None:
    """This machine's Tailscale IPv4 (the launcher asks; the dashboard package runs no process)."""
    app = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    exe = shutil.which("tailscale") or (app if os.path.exists(app) else None)
    try:
        if exe:
            r = spawn.run([exe, "ip", "-4"], timeout_s=3.0)
            if r.exit == 0 and r.out.strip():
                return r.out.strip().splitlines()[0]
        for cmd in (["ip", "-4", "-o", "addr"], ["ifconfig"]):
            for ip in dash.inet_addrs(spawn.run(cmd, timeout_s=3.0).out):
                if ipaddress.ip_address(ip) in dash_bind.CGNAT:
                    return ip
    except OSError:
        pass
    return None


def run(op: str, env: Env, spawner: Spawner, installed: Mapping[str, int]) -> int:
    home = default_root(env) if op in ("status", "stop", "url") else config_dir(env)
    return dash.launch(op, env, spawner, lambda: tailscale_ip(spawner), installed, PLUGIN_ROOT, home)
