"""Start the dash: parse the command line, refuse a bind that must not happen, bind every address or none, serve, and exit after
hours with no task-loop event and no page request."""

import argparse
import os
import sys
import threading
import time
from collections.abc import Sequence
from http.server import ThreadingHTTPServer
from pathlib import Path

from taskloop.contracts.env import Env as ProcessEnv
from taskloop.contracts.envvars import EnvVar
from taskloop_dash import bind
from taskloop_dash.app import Dash
from taskloop_dash.env import Env
from taskloop_dash.http import make_handler

IDLE_CHECK = 300  # seconds between idle checks
STATIC = Path(__file__).resolve().parent / "static"


def idle_watch(dash: Dash, hours: float) -> None:
    env = dash.env
    while True:
        time.sleep(IDLE_CHECK)
        try:
            last_event = env.config.events().stat().st_mtime
        except OSError:
            last_event = env.started
        if env.clock() - max(last_event, env.last_seen, env.started) > hours * 3600:
            os._exit(0)


def start(env: Env, here: Path, process: ProcessEnv,
          argv: Sequence[str] | None = None) -> tuple[list[ThreadingHTTPServer], list[str], int, Dash]:
    """Parse the command line, refuse a bind that must not happen (exit 2), bind every address or none (exit 2), and set the handler.
    -> (the bound servers, their addresses, the port, the Dash). `here` is the folder of the code that was started (the installed-copy and
    dev-checkout rules look at it). Nothing is served yet."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--bind", default=None, help="comma-separated addresses (default: loopback + Tailscale; dev checkout: loopback)")
    a = ap.parse_args(argv)
    dev = bind.is_dev_checkout(here)
    addrs, port = bind.plan(a.port, a.bind, dev, process)
    why = bind.bind_refusal(addrs, port, here, env.home, env.config.root, process)
    if why:
        print(why, file=sys.stderr, flush=True)
        sys.exit(2)
    bind.token(env.config.root)
    try:
        servers = bind.open_servers(addrs, port, None)  # the handler is set below: it needs the real port
    except bind.BindError as e:
        print(e, file=sys.stderr, flush=True)
        sys.exit(2)
    port = servers[0].server_address[1]
    dash = Dash(env)
    handler = make_handler(dash, port, addrs, STATIC,
                           lambda: bind.token(env.config.root), str(Path(sys.argv[0]).resolve()))
    for s in servers:
        s.RequestHandlerClass = handler
    if not bind.is_dev_checkout(here):  # a dev server must not claim the shared pid file
        env.config.root.mkdir(parents=True, exist_ok=True)
        tmp = env.config.root / "dash.pid.tmp"
        tmp.write_text(str(os.getpid()))
        os.replace(tmp, env.config.root / "dash.pid")  # a reader never sees the file empty
    return servers, addrs, port, dash


def main(env: Env, here: Path, process: ProcessEnv, argv: Sequence[str] | None = None) -> None:
    servers, addrs, port, dash = start(env, here, process, argv)
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    threading.Thread(target=idle_watch, args=(dash, float(process.get(EnvVar.TASK_LOOP_DASH_IDLE_H, "6"))), daemon=True).start()
    print("task-loop dashboard {} on {}".format(env.version, ", ".join(bind.urls(addrs, port))), flush=True)
    servers[0].serve_forever()
