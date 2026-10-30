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
from taskloop.app.wire import real
from taskloop.contracts import env as penv
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ports import Spawner
from taskloop_dash import bind as dash_bind
from taskloop_dash.cli import dash as dash_cli

SRC: Final = PLUGIN_ROOT / "src"  # where `--ports taskloop.app.launch.dash_ports:ports` is found
VENDOR: Final = PLUGIN_ROOT / "skills" / "task-loop" / "_vendor"
DASH: Final = SRC / "taskloop_dash" / "__main__.py"  # the script a running `python3 -m taskloop_dash` reports
PORT: Final = int(penv.ambient(EnvVar.TASK_LOOP_DASH_PORT, "7878"))


def code_version() -> str:
    return dash_cli.code_version()


def inet_addrs(listing: str) -> list[str]:
    """The IPv4 addresses after 'inet ' in `ip -o addr` / `ifconfig` output."""
    words = listing.split()
    ips = [after.split("/")[0] for word, after in itertools.pairwise(words) if word == "inet"]
    return [ip for ip in ips if ip.count(".") == 3 and all(p.isdigit() for p in ip.split("."))]


def tailscale_ip(spawner: Spawner | None = None) -> str | None:
    """This machine's Tailscale IPv4 (the launcher asks; the dashboard server runs no process)."""
    app = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    spawn = spawner or real.spawner()
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


def default_binds() -> list[str]:
    """What the installed server binds: TASK_LOOP_DASH_BIND, else loopback and the Tailscale address."""
    given = [x.strip() for x in penv.ambient(EnvVar.TASK_LOOP_DASH_BIND).split(",") if x.strip()]
    if given:
        return given
    ts = tailscale_ip()
    return ["127.0.0.1"] + ([ts] if ts else [])


def expected_binds() -> list[str]:
    """The addresses the installed server would bind now."""
    return default_binds()


def is_dev_checkout() -> bool:
    return dash_bind.is_dev_checkout(PLUGIN_ROOT)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def ping(port: int | None = None) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port or PORT}/api/version", timeout=1.5) as r:
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


def stop_server(v: dict[str, Any] | None = None, port: int | None = None, spawner: Spawner | None = None) -> None:
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
    (spawner or real.spawner()).stop_pid(pid)
    for _ in range(20):
        if not ping(port):
            return
        time.sleep(0.2)


def log_tail(n: int = 5) -> str:
    try:
        return "\n".join((config_dir() / "dash.log").read_text(errors="replace").strip().splitlines()[-n:])
    except OSError:
        return ""


def start_server(port: int, bind: str | None = None, spawner: Spawner | None = None) -> tuple[dict[str, Any] | None, str]:
    """Start detached; wait until it answers. Returns (version dict or None, failure text)."""
    log = open(config_dir() / "dash.log", "ab")  # noqa: SIM115  the detached child keeps it
    env = {k: val for k, val in penv.snapshot().vars.items() if not k.startswith(("CLAUDE_CODE_SESSION", "DELEGATE_", "CODEX_COMPANION"))}
    more = [env["PYTHONPATH"]] if env.get("PYTHONPATH") else []
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), str(VENDOR), *more])
    bind = bind or ",".join(default_binds())
    # sys.executable, not uv: the server imports taskloop.contracts (msgspec), and tl.py, which starts it, runs under `uv run --script`
    cmd = [sys.executable, "-m", "taskloop_dash", "--ports", "taskloop.app.launch.dash_ports:ports", "--port", str(port), "--bind", bind]
    proc = (spawner or real.spawner()).start(cmd, env=env, cwd=str(config_dir()), out=log)
    for _ in range(40):
        if proc.poll() not in (None, 0):
            return None, f"dashboard exited {proc.poll()}: {log_tail() or 'see ' + str(config_dir() / 'dash.log')}"
        v = ping(port)
        if v:
            return v, ""
        time.sleep(0.25)
    return None, "dashboard did not start; see " + str(config_dir() / "dash.log")


def print_urls(v: dict[str, Any] | None) -> None:
    for u in (v or {}).get("urls", [f"http://127.0.0.1:{PORT}"]):
        print("DASHBOARD " + u)


def ensure_dev() -> int:
    """tests/dev: own random loopback port; the installed server on :7878 stays untouched."""
    v, err = start_server(free_port(), "127.0.0.1")
    if not v:
        print("tl: " + err)
        return 1
    print_urls(v)
    return 0


def ensure() -> int:
    """Running and current, else replace it (a stale one: files deleted, old version, or missing an address)."""
    v = ping()
    if v and not is_dash_server(v):
        print(f"tl: port {PORT} is held by something that is not a task-loop dashboard; not touching it")
        return 1
    if v:
        why = stale_reason(v, code_version(), expected_binds())
        if not why:
            print_urls(v)
            return 0
        print("tl: replacing the running dashboard (pid {}): {}".format(v.get("pid"), why))
        stop_server(v)
        if ping():
            print("tl: could not stop the running dashboard (pid {})".format(v.get("pid")))
            return 1
    v, err = start_server(PORT)
    if not v:
        print("tl: " + err)
        return 1
    print_urls(v)
    return 0


def url() -> int:
    v = ping()
    print_urls(v)
    try:  # the links that may answer asks: open one on the phone once, the page keeps the token
        t = (config_dir() / "dash.token").read_text().strip()
    except OSError:
        t = ""
    for u in (v or {}).get("urls", []) if t else []:
        print(f"ANSWER LINK {u}/?token={t}")
    return 0


def run(op: str) -> int:
    dev = is_dev_checkout() and not penv.ambient_set(EnvVar.TASK_LOOP_DASH_PORT)
    if dev and op == "ensure":
        return ensure_dev()
    if op == "stop":
        v = ping()
        if not (dev and v and v.get("script") != str(DASH)):  # never stop the installed server from a dev checkout
            stop_server(v)
        return 0
    if op == "status":
        v = ping()
        print(json.dumps(v) if v else "DOWN")
        return 0 if v else 1
    return url() if op == "url" else ensure()
