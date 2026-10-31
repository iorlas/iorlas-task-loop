"""The dashboard server of this machine (one per user): is it up, is it current, start it detached, stop it; and `tl dash ...`."""
import ipaddress
import itertools
import json
import os
import shutil
import socket
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Final

from taskloop.adapters.ident import PLUGIN_ROOT, config_dir
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ports import Spawner
from taskloop_dash import bind as dash_bind
from taskloop_dash.cli import dash as dash_cli

SRC: Final = PLUGIN_ROOT / "src"  # where `--ports taskloop.app.launch.dash_ports:ports` is found
VENDOR: Final = PLUGIN_ROOT / "skills" / "task-loop" / "_vendor"
DASH: Final = SRC / "taskloop_dash" / "__main__.py"  # the script a running `python3 -m taskloop_dash` reports
DEFAULT_PORT: Final = 7878


def port_of(env: Env) -> int:
    """The installed server's port: TASK_LOOP_DASH_PORT, else 7878."""
    return int(env.get(EnvVar.TASK_LOOP_DASH_PORT, str(DEFAULT_PORT)))


def code_version() -> str:
    return dash_cli.code_version()


def inet_addrs(listing: str) -> list[str]:
    """The IPv4 addresses after 'inet ' in `ip -o addr` / `ifconfig` output."""
    words = listing.split()
    ips = [after.split("/")[0] for word, after in itertools.pairwise(words) if word == "inet"]
    return [ip for ip in ips if ip.count(".") == 3 and all(p.isdigit() for p in ip.split("."))]


def tailscale_ip(spawn: Spawner) -> str | None:
    """This machine's Tailscale IPv4 (the launcher asks; the dashboard server runs no process)."""
    app = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    exe = shutil.which("tailscale") or (app if os.path.exists(app) else None)
    try:
        if exe:
            r = spawn.run([exe, "ip", "-4"], timeout_s=3.0)
            if r.exit == 0 and r.out.strip():
                return r.out.strip().splitlines()[0]
        for cmd in (["ip", "-4", "-o", "addr"], ["ifconfig"]):
            for ip in inet_addrs(spawn.run(cmd, timeout_s=3.0).out):
                if ipaddress.ip_address(ip) in dash_bind.CGNAT:
                    return ip
    except OSError:
        pass
    return None


def default_binds(env: Env, spawner: Spawner) -> list[str]:
    """What the installed server binds: TASK_LOOP_DASH_BIND, else loopback and the Tailscale address."""
    given = [x.strip() for x in env.get(EnvVar.TASK_LOOP_DASH_BIND).split(",") if x.strip()]
    if given:
        return given
    ts = tailscale_ip(spawner)
    return ["127.0.0.1"] + ([ts] if ts else [])


def expected_binds(env: Env, spawner: Spawner) -> list[str]:
    """The addresses the installed server would bind now."""
    return default_binds(env, spawner)


def is_dev_checkout() -> bool:
    return dash_bind.is_dev_checkout(PLUGIN_ROOT)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def ping(port: int) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=1.5) as r:
            got = json.loads(r.read())
            return got if isinstance(got, dict) else None
    except Exception:
        return None


def is_dash_server(v: object) -> bool:
    """Shape of a task-loop dashboard's /api/version: the only thing ensure may stop."""
    return isinstance(v, dict) and all(k in v for k in ("version", "pid", "urls", "started"))


def stale_reason(v: dict[str, Any], version: str, want: list[str]) -> str | None:
    """Why a running dashboard must be replaced, else None."""
    script = v.get("script")
    if not script:
        return "it predates script/binds reporting"
    if not Path(script).exists():
        return "its script is gone: " + script
    if v.get("version") != version:
        return f"version {v.get('version')} differs from installed {version}"
    missing = [a for a in want if a not in (v.get("binds") or [])]
    if missing:
        return "it does not serve " + ", ".join(missing)
    return None


def stop_server(v: dict[str, Any] | None, port: int, spawner: Spawner) -> None:
    """Stop the task-loop server that answers on the port (its own pid, never a stale pidfile's)."""
    v = v or ping(port)
    if not v or not is_dash_server(v) or not v.get("pid"):
        return
    try:
        pid = int(v["pid"])
    except ValueError:
        return
    if pid in (os.getpid(), os.getppid()) or pid <= 1:  # a server that names this very process is a test's, not ours to stop
        return
    spawner.stop_pid(pid)
    for _ in range(20):
        if not ping(port):
            return
        time.sleep(0.2)


def log_tail(env: Env, n: int = 5) -> str:
    try:
        return "\n".join((config_dir(env) / "dash.log").read_text(errors="replace").strip().splitlines()[-n:])
    except OSError:
        return ""


def start_server(port: int, env: Env, spawner: Spawner, bind: str | None = None) -> tuple[dict[str, Any] | None, str]:
    """Start detached; wait until it answers. Returns (version dict or None, failure text)."""
    home = config_dir(env)
    log = open(home / "dash.log", "ab")  # noqa: SIM115  the detached child keeps it
    more = [env.get("PYTHONPATH")] if env.get("PYTHONPATH") else []
    path = {"PYTHONPATH": os.pathsep.join([str(SRC), str(VENDOR), *more])}  # the server imports taskloop.contracts: not in the allowlist
    bind = bind or ",".join(default_binds(env, spawner))
    # sys.executable, not uv: the server imports taskloop.contracts (msgspec), and tl.py, which starts it, runs under `uv run --script`
    cmd = [sys.executable, "-m", "taskloop_dash", "--ports", "taskloop.app.launch.dash_ports:ports", "--port", str(port), "--bind", bind]
    proc = spawner.start(cmd, extra=path, cwd=str(home), out=log)
    for _ in range(40):
        if proc.poll() not in (None, 0):
            return None, f"dashboard exited {proc.poll()}: {log_tail(env) or 'see ' + str(home / 'dash.log')}"
        v = ping(port)
        if v:
            return v, ""
        time.sleep(0.25)
    return None, "dashboard did not start; see " + str(home / "dash.log")


def print_urls(v: dict[str, Any] | None, port: int) -> None:
    for u in (v or {}).get("urls", [f"http://127.0.0.1:{port}"]):
        print("DASHBOARD " + u)


def ensure_dev(env: Env, spawner: Spawner) -> int:
    """tests/dev: own random loopback port; the installed server on :7878 stays untouched."""
    port = free_port()
    v, err = start_server(port, env, spawner, "127.0.0.1")
    if not v:
        print("tl: " + err)
        return 1
    print_urls(v, port)
    return 0


def ensure(env: Env, spawner: Spawner) -> int:
    """Running and current, else replace it (a stale one: files deleted, old version, or missing an address)."""
    (config_dir(env) / "dash.token").unlink(missing_ok=True)  # the dash had a token once; it has no auth now
    port = port_of(env)
    v = ping(port)
    if v and not is_dash_server(v):
        print(f"tl: port {port} is held by something that is not a task-loop dashboard; not touching it")
        return 1
    if v:
        why = stale_reason(v, code_version(), expected_binds(env, spawner))
        if not why:
            print_urls(v, port)
            return 0
        print("tl: replacing the running dashboard (pid {}): {}".format(v.get("pid"), why))
        stop_server(v, port, spawner)
        if ping(port):
            print("tl: could not stop the running dashboard (pid {})".format(v.get("pid")))
            return 1
    v, err = start_server(port, env, spawner)
    if not v:
        print("tl: " + err)
        return 1
    print_urls(v, port)
    return 0


def url(env: Env) -> int:
    port = port_of(env)
    v = ping(port)
    print_urls(v, port)
    return 0


def run(op: str, env: Env, spawner: Spawner) -> int:
    port = port_of(env)
    dev = is_dev_checkout() and EnvVar.TASK_LOOP_DASH_PORT not in env
    if dev and op == "ensure":
        return ensure_dev(env, spawner)
    if op == "stop":
        v = ping(port)
        if not (dev and v and v.get("script") != str(DASH)):  # never stop the installed server from a dev checkout
            stop_server(v, port, spawner)
        return 0
    if op == "status":
        v = ping(port)
        print(json.dumps(v) if v else "DOWN")
        return 0 if v else 1
    return url(env) if op == "url" else ensure(env, spawner)
