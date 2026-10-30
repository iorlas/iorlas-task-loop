"""A Dash over a temp state dir for a test: `make_dash(config=...)` reads XDG_CONFIG_HOME when no config is given, so make it after
the environment is patched. Its bd is the engine's adapter over whatever `bd` is on PATH (the launcher wires the same)."""
import contextlib
import shutil
import threading

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from taskloop.adapters.bd import BdStore
from taskloop.contracts.env import snapshot
from taskloop_dash import serve
from taskloop_dash.app import Dash
from taskloop_dash.cli import dash as dash_cli
from taskloop_dash.env import Env, Ports


def adapter_store(repo):
    if not shutil.which("bd"):
        raise OSError(2, "bd is not installed")
    return BdStore("tl-dash", repo or None)


def make_dash(ports=None, **kw):
    return Dash(Env(ports=ports or Ports(store=adapter_store), **kw))


@contextlib.contextmanager
def serving(ports=None, *argv):
    """The dash server (the code `python3 -m taskloop_dash` starts, minus the process): a real socket served from a thread. Yields its
    base URL. The environment (HOME, XDG_CONFIG_HOME, TASK_LOOP_DASH_BIND) is read now, so patch it first."""
    env = Env(ports=ports or Ports(), version=dash_cli.code_version())
    servers, _addrs, port, _dash = serve.start(env, dash_cli.PACKAGE, snapshot(), list(argv) or ["--port", "0"])
    thread = threading.Thread(target=servers[0].serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        servers[0].shutdown()
        for s in servers:
            s.server_close()
        thread.join(5)


__all__ = ["Dash", "Env", "Ports", "adapter_store", "make_dash", "serving"]
