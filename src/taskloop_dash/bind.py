"""Where the dash may listen: loopback and the Tailscale range only (there is no auth: the bind is the whole access rule), the
dev-checkout rules, and the bind itself."""

import ipaddress
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from taskloop.contracts.env import Env as ProcessEnv
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.paths import ConfigDir

CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's range
DEFAULT_PORT = 7878


class BindError(Exception):
    pass


def allowed_addr(addr: str) -> bool:
    """True for `localhost`, loopback and the Tailscale CGNAT range: the only addresses the dash may listen on."""
    if addr == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(addr.split("%", maxsplit=1)[0])
    except ValueError:
        return False
    return ip.is_loopback or ip in CGNAT


def bind_addrs(process: ProcessEnv) -> list[str]:
    given = process.get(EnvVar.TASK_LOOP_DASH_BIND)
    if given:
        return [x.strip() for x in given.split(",") if x.strip()]
    return ["127.0.0.1"]  # the launcher (`tl dash`) names a Tailscale address with --bind; the server looks at no network tool


def is_dev_checkout(here: Path | str) -> bool:
    """A git checkout or worktree (tests, dev) rather than the installed plugin cache."""
    path = Path(here).resolve()
    if "cache" in path.parts and "plugins" in path.parts:
        return False
    return any((d / ".git").exists() for d in [path, *path.parents])


def plan(port: int | None, bind: str | None, dev: bool, process: ProcessEnv) -> tuple[list[str], int]:
    """(addresses, port): installed copy = loopback + Tailscale on 7878; a dev checkout = loopback on a random port."""
    if bind:
        addrs = [x.strip() for x in bind.split(",") if x.strip()]
    elif dev and not process.get(EnvVar.TASK_LOOP_DASH_BIND):
        addrs = ["127.0.0.1"]
    else:
        addrs = bind_addrs(process)
    return addrs, (port if port is not None else (0 if dev else DEFAULT_PORT))


def is_installed_copy(here: Path | str, home: Path | str) -> bool:
    """True only when `here` really lives (symlinks resolved) under ~/.claude/plugins/cache/."""
    cache = (Path(home) / ".claude" / "plugins" / "cache").resolve()
    try:
        Path(here).resolve().relative_to(cache)
    except ValueError:
        return False
    return True


def is_loopback(addr: str) -> bool:
    if addr == "localhost":
        return True
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def bind_refusal(addrs: list[str], port: int, here: Path | str, home: Path | str, state: Path | str, process: ProcessEnv) -> str | None:
    """Why this server must not bind, else None: a dev copy once took :7878 on the Tailscale address with an empty state dir and
    blanked the phone dashboard. Only TASK_LOOP_DASH_DEV_PUBLIC=1 overrides that; nothing overrides an address outside loopback and
    Tailscale (0.0.0.0, the LAN): the dash has no auth."""
    if outside := [a for a in addrs if not allowed_addr(a)]:
        return "refusing to bind {}: the dashboard has no auth, so it listens only on loopback and Tailscale (100.64.0.0/10)".format(
            ", ".join(outside))
    if not is_installed_copy(here, home) and process.get(EnvVar.TASK_LOOP_DASH_DEV_PUBLIC) != "1":
        bad = [a for a in addrs if not is_loopback(a)]
        if bad or port == DEFAULT_PORT:
            return (
                "refusing to bind {}: only the installed plugin copy (under ~/.claude/plugins/cache/) may serve "
                "a non-loopback address or port 7878; set TASK_LOOP_DASH_DEV_PUBLIC=1 to override"
            ).format(", ".join(bad) if bad else "port 7878")
    if port == DEFAULT_PORT and not ConfigDir(state).repos().is_file():
        return "refusing to start on port 7878: no repos.json in the state dir (run `tl register` first)"
    return None


def open_servers(addrs: list[str], port: int, handler: Any) -> list[ThreadingHTTPServer]:
    """Bind every address or none: a partial set would silently serve a subset."""
    servers: list[ThreadingHTTPServer] = []
    for addr in addrs:
        try:
            # port 0: every address after the first reuses the port the first was given
            servers.append(ThreadingHTTPServer((addr, servers[0].server_address[1] if servers else port), handler))
        except OSError as e:
            p = servers[0].server_address[1] if servers else port
            for s in servers:
                s.server_close()
            raise BindError(f"bind {addr}:{p} failed: {e}") from e
    return servers


def urls(addrs: list[str], port: int) -> list[str]:
    return [f"http://{a}:{port:d}" for a in addrs]


