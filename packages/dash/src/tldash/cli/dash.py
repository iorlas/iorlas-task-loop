"""Dashboard launch rules for the shell and `python3 -m tldash`.

The engine code is not imported here: `--ports MODULE:FUNC` names a callable that
returns the `Ports` (the launcher, tl.py, supplies one), resolved by the injected `load`; with no `--ports` the dash serves its own files
and says nothing for the facts only the engine holds."""

import argparse
import hashlib
import importlib
import ipaddress
import itertools
import json
import os
import socket
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import tlkernel as contracts
from tlkernel import env as penv
from tlkernel.dash import READ_PROTOCOL
from tlkernel.env import Env as ProcessEnv
from tlkernel.envvars import EnvVar
from tlkernel.factorydb import declare_needs, declare_parts
from tlkernel.paths import default_root
from tlkernel.procport import Spawner

from tldash import bind as dash_bind
from tldash import serve
from tldash.env import Env, Ports
from tldash.needs import NEEDS
from tldash.parts import DASH_PARTS

PACKAGE = Path(__file__).resolve().parents[1]
CONTRACTS = Path(contracts.__file__).resolve().parent  # the records it reads and the commands it sends
SKIP_DIRS = frozenset({"__pycache__"})


def code_version(*packages: Path) -> str:
    """A short hash of every file of the dash package and of the contracts it imports: a running dash from older code, or from
    older contracts than the engine now writes, is replaced."""
    h = hashlib.sha256()
    for package in packages or (PACKAGE, CONTRACTS):
        for p in sorted(package.rglob("*")):
            if p.is_file() and not SKIP_DIRS.intersection(p.parts):
                h.update(p.relative_to(package).as_posix().encode())
                h.update(p.read_bytes())
    return h.hexdigest()[:12]


def resolve_ports(spec: str | None, env: penv.Env, load: Callable[[str], ModuleType] = importlib.import_module) -> Ports:
    """`module:func` -> the Ports that function returns; no spec -> Ports() that say nothing."""
    if not spec:
        return Ports()
    module, _, func = spec.partition(":")
    return getattr(load(module), func or "ports")(env)


def main(argv: Sequence[str] | None = None, load: Callable[[str], ModuleType] = importlib.import_module,
         here: Path = PACKAGE) -> None:
    declare_parts(DASH_PARTS)
    declare_needs(NEEDS)
    ap = argparse.ArgumentParser(prog="python3 -m tldash", add_help=False, allow_abbrev=False)
    ap.add_argument("--ports", default=None, help="MODULE:FUNC returning the Ports (the engine's read-only facts)")
    known, rest = ap.parse_known_args(argv)
    process = penv.snapshot()
    env = Env(config=default_root(process), ports=resolve_ports(known.ports, process, load), version=code_version(),
              host=socket.gethostname())
    serve.main(env, here, process, rest)  # the dash's edge: the process environment is taken here, once


DEFAULT_PORT = dash_bind.DEFAULT_PORT


def port_of(env: ProcessEnv) -> int:
    """The installed server's port: TASK_LOOP_DASH_PORT, else 7878."""
    return int(env.get(EnvVar.TASK_LOOP_DASH_PORT, str(DEFAULT_PORT)))


def inet_addrs(listing: str) -> list[str]:
    """The IPv4 addresses after 'inet ' in `ip -o addr` / `ifconfig` output."""
    words = listing.split()
    ips = [after.split("/")[0] for word, after in itertools.pairwise(words) if word == "inet"]
    return [ip for ip in ips if ip.count(".") == 3 and all(p.isdigit() for p in ip.split("."))]


def tailscale_ip(exe: str | None, ask: Callable[[list[str]], tuple[int, str]]) -> str | None:
    """Pick this machine's Tailscale IPv4 from the binary or interface listings."""
    try:
        if exe:
            code, out = ask([exe, "ip", "-4"])
            if code == 0 and out.strip():
                return out.strip().splitlines()[0]
        for cmd in (["ip", "-4", "-o", "addr"], ["ifconfig"]):
            for ip in inet_addrs(ask(cmd)[1]):
                if ipaddress.ip_address(ip) in dash_bind.CGNAT:
                    return ip
    except OSError:
        pass
    return None


def default_binds(env: ProcessEnv, tailscale: Callable[[], str | None]) -> list[str]:
    """What the installed server binds: TASK_LOOP_DASH_BIND, else loopback and the Tailscale address."""
    given = [x.strip() for x in env.get(EnvVar.TASK_LOOP_DASH_BIND).split(",") if x.strip()]
    if given:
        return given
    ts = tailscale()
    return ["127.0.0.1"] + ([ts] if ts else [])


def expected_binds(env: ProcessEnv, tailscale: Callable[[], str | None]) -> list[str]:
    """The addresses the installed server would bind now."""
    return default_binds(env, tailscale)


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


def _wire_reason(v: dict[str, object], installed: Mapping[str, int]) -> str | None:
    """Why the server's read protocol or factory.db parts do not fit the installed code, else None."""
    if v.get("protocol") != READ_PROTOCOL:
        return f"it speaks read protocol {v.get('protocol')}, installed is {READ_PROTOCOL}"
    needs, parts = v.get("needs"), v.get("parts")
    if not isinstance(needs, dict) or not isinstance(parts, dict):
        return "it reports no part needs or versions"
    for name, want in needs.items():
        found = installed.get(name, 0)
        if reason := _part_reason(name, want, parts.get(name), found):
            return reason
    return None


def _part_reason(name: str, want: object, upper: object, found: int) -> str | None:
    if not isinstance(want, int):
        return f"invalid need for part {name}"
    if found < want:
        return f"it needs part {name} v{want}, installed is v{found}"
    if not isinstance(upper, int):
        return f"it reports no readable version for part {name}"
    if found > upper:
        return f"installed part {name} is v{found}, it reads up to v{upper}"
    return None


def stale_reason(v: dict[str, Any], version: str, want: list[str], installed: Mapping[str, int]) -> str | None:
    """Why a running dashboard must be replaced, else None."""
    script = v.get("script")
    if not script:
        return "it predates script/binds reporting"
    if not Path(script).exists():
        return "its script is gone: " + script
    if v.get("version") != version:
        return f"version {v.get('version')} differs from installed {version}"
    wire = _wire_reason(v, installed)
    if wire:
        return wire
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


def log_tail(home: Path, n: int = 5) -> str:
    try:
        return "\n".join((home / "dash.log").read_text(errors="replace").strip().splitlines()[-n:])
    except OSError:
        return ""


def start_server(port: int, env: ProcessEnv, spawner: Spawner, tailscale: Callable[[], str | None], root: Path, home: Path,
                 bind: str | None = None) -> tuple[dict[str, Any] | None, str]:
    """Start detached; wait until it answers. Returns (version dict or None, failure text)."""
    log = open(home / "dash.log", "ab")  # noqa: SIM115  the detached child keeps it
    more = [env.get("PYTHONPATH")] if env.get("PYTHONPATH") else []
    path = {"PYTHONPATH": os.pathsep.join([
        str(root / "src"), str(root / "packages/dash/src"), str(root / "skills/task-loop/_vendor"), *more,
    ])}  # the server imports tlkernel: not in the allowlist
    bind = bind or ",".join(default_binds(env, tailscale))
    # sys.executable, not uv: the server imports tlkernel (msgspec), and tl.py, which starts it, runs under `uv run --script`
    cmd = [sys.executable, "-m", "tldash", "--ports", "taskloop.app.launch.dash_ports:ports", "--port", str(port), "--bind", bind]
    proc = spawner.start(cmd, extra=path, cwd=str(home), out=log)
    for _ in range(40):
        if proc.poll() not in (None, 0):
            return None, f"dashboard exited {proc.poll()}: {log_tail(home) or 'see ' + str(home / 'dash.log')}"
        v = ping(port)
        if v:
            return v, ""
        time.sleep(0.25)
    return None, "dashboard did not start; see " + str(home / "dash.log")


def print_urls(v: dict[str, Any] | None, port: int) -> None:
    for u in (v or {}).get("urls", [f"http://127.0.0.1:{port}"]):
        print("DASHBOARD " + u)


def ensure_dev(env: ProcessEnv, spawner: Spawner, tailscale: Callable[[], str | None], root: Path, home: Path) -> int:
    """tests/dev: own random loopback port; the installed server on :7878 stays untouched."""
    port = free_port()
    v, err = start_server(port, env, spawner, tailscale, root, home, "127.0.0.1")
    if not v:
        print("tl: " + err)
        return 1
    print_urls(v, port)
    return 0


def ensure(env: ProcessEnv, spawner: Spawner, tailscale: Callable[[], str | None], installed: Mapping[str, int],
           root: Path, home: Path) -> int:
    """Running and current, else replace it (a stale one: files deleted, old version, or missing an address)."""
    (home / "dash.token").unlink(missing_ok=True)  # the dash had a token once; it has no auth now
    port = port_of(env)
    v = ping(port)
    if v and not is_dash_server(v):
        print(f"tl: port {port} is held by something that is not a task-loop dashboard; not touching it")
        return 1
    if v:
        why = stale_reason(v, code_version(), expected_binds(env, tailscale), installed)
        if not why:
            print_urls(v, port)
            return 0
        print("tl: replacing the running dashboard (pid {}): {}".format(v.get("pid"), why))
        stop_server(v, port, spawner)
        if ping(port):
            print("tl: could not stop the running dashboard (pid {})".format(v.get("pid")))
            return 1
    v, err = start_server(port, env, spawner, tailscale, root, home)
    if not v:
        print("tl: " + err)
        return 1
    print_urls(v, port)
    return 0


def url(env: ProcessEnv) -> int:
    port = port_of(env)
    v = ping(port)
    print_urls(v, port)
    return 0


def launch(op: str, env: ProcessEnv, spawner: Spawner, tailscale: Callable[[], str | None], installed: Mapping[str, int],
           root: Path, home: Path) -> int:
    port = port_of(env)
    dev = dash_bind.is_dev_checkout(root) and EnvVar.TASK_LOOP_DASH_PORT not in env
    if dev and op == "ensure":
        return ensure_dev(env, spawner, tailscale, root, home)
    if op == "stop":
        v = ping(port)
        # Never stop the installed server from a dev checkout.
        if not (dev and v and v.get("script") != str(root / "packages/dash/src/tldash/__main__.py")):
            stop_server(v, port, spawner)
        return 0
    if op == "status":
        v = ping(port)
        print(json.dumps(v) if v else "DOWN")
        return 0 if v else 1
    return url(env) if op == "url" else ensure(env, spawner, tailscale, installed, root, home)
