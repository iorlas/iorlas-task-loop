"""A Dash over a temp state dir for a test: `make_dash(config=...)` reads XDG_CONFIG_HOME when no config is given, so make it after
the environment is patched. Its bd is the engine's adapter over whatever `bd` is on PATH (the launcher wires the same)."""
import contextlib
import shutil
import threading

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from taskloop.adapters.bd import BdStore
from tldash import serve
from tldash.app import Dash
from tldash.cli import dash as dash_cli
from tldash.env import Env, Ports
from tlkernel.env import snapshot
from tlkernel.paths import default_root


def adapter_store(repo):
    if not shutil.which("bd"):
        raise OSError(2, "bd is not installed")
    return BdStore("tl-dash", repo or None)


def make_dash(ports=None, config=None, **kw):
    return Dash(Env(config or default_root(snapshot()), ports=ports or Ports(store=adapter_store), **kw))


@contextlib.contextmanager
def serving(ports=None, *argv):
    """The dash server (the code `python3 -m tldash` starts, minus the process): a real socket served from a thread. Yields its
    base URL. The environment (HOME, XDG_CONFIG_HOME, TASK_LOOP_DASH_BIND) is read now, so patch it first."""
    env = Env(config=default_root(snapshot()), ports=ports or Ports(), version=dash_cli.code_version())
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
