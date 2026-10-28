"""Where the dash may listen and who may write: loopback and the Tailscale range, the dev-checkout rules, and the bind itself."""

import contextlib
import hmac
import ipaddress
import os
import secrets
import socket
from collections.abc import Callable
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's range
DEFAULT_PORT = 7878


class BindError(Exception):
    pass


def trusted_source(addr: object) -> bool:
    """True for loopback and the Tailscale CGNAT range: the owner's own machines, which answer asks with no token. addr is the
    socket's peer (client_address), never a header: a proxy header is the client's to forge."""
    try:
        ip = ipaddress.ip_address(str(addr).split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip in CGNAT


def token(state_dir: Path) -> str:
    """A secret for answer POSTs from outside loopback and Tailscale, made once (0600)."""
    f = state_dir / "dash.token"
    try:
        t = f.read_text().strip()
        if t:
            return t
    except OSError:
        pass
    state_dir.mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(24)
    f.write_text(t)
    with contextlib.suppress(OSError):
        os.chmod(f, 0o600)
    return t


def post_allowed(addr: object, authorization: str | None, secret: Callable[[], str]) -> bool:
    """A POST needs no token from a trusted source; any other source (a container bound to 0.0.0.0, the LAN) needs it."""
    if trusted_source(addr):
        return True
    got = (authorization or "").replace("Bearer ", "", 1).strip()
    return bool(got) and hmac.compare_digest(got, secret())


def bind_addrs() -> list[str]:
    env = os.environ.get("TASK_LOOP_DASH_BIND")
    if env:
        return [x.strip() for x in env.split(",") if x.strip()]
    return ["127.0.0.1"]  # the launcher (`tl dash`) names a Tailscale address with --bind; the server looks at no network tool


def is_dev_checkout(here: Path | str) -> bool:
    """A git checkout or worktree (tests, dev) rather than the installed plugin cache."""
    path = Path(here).resolve()
    if "cache" in path.parts and "plugins" in path.parts:
        return False
    return any((d / ".git").exists() for d in [path, *path.parents])


def plan(port: int | None, bind: str | None, dev: bool) -> tuple[list[str], int]:
    """(addresses, port): installed copy = loopback + Tailscale on 7878; a dev checkout = loopback on a random port."""
    if bind:
        addrs = [x.strip() for x in bind.split(",") if x.strip()]
    elif dev and not os.environ.get("TASK_LOOP_DASH_BIND"):
        addrs = ["127.0.0.1"]
    else:
        addrs = bind_addrs()
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


def bind_refusal(addrs: list[str], port: int, here: Path | str, home: Path | str, state: Path | str) -> str | None:
    """Why this server must not bind, else None: a dev copy once took :7878 on the Tailscale address with an empty state dir and
    blanked the phone dashboard. Only TASK_LOOP_DASH_DEV_PUBLIC=1 overrides."""
    if not is_installed_copy(here, home) and os.environ.get("TASK_LOOP_DASH_DEV_PUBLIC") != "1":
        bad = [a for a in addrs if not is_loopback(a)]
        if bad or port == DEFAULT_PORT:
            return (
                "refusing to bind {}: only the installed plugin copy (under ~/.claude/plugins/cache/) may serve "
                "a non-loopback address or port 7878; set TASK_LOOP_DASH_DEV_PUBLIC=1 to override"
            ).format(", ".join(bad) if bad else "port 7878")
    if port == DEFAULT_PORT and not (Path(state) / "repos.json").is_file():
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
            raise BindError(f"bind {addr}:{int(p)} failed: {e}") from e
    return servers


def urls(addrs: list[str], port: int) -> list[str]:
    return ["http://{}:{:d}".format(socket.gethostname() if a == "0.0.0.0" else a, int(port)) for a in addrs]


