#!/usr/bin/env python3
"""task-loop dashboard launcher: `python3 server.py [--port 7878]`, started by `tl.py dash ensure`.

The dashboard itself is the package src/taskloop_dash (it imports taskloop.contracts and nothing else). This file is the one place that
knows the flat engine code: it hands the package the few read-only facts that live there (slot beads, the waiting line, a repo's
config, the installed versions, the run reflections) as callables, and gives tl.py the entry points it calls (plan, is_dev_checkout, inbox, answer, withdraw). It goes when src/taskloop_dash/cli/dash.py replaces it."""

import hashlib
import shutil
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "src"))
from taskloop.adapters.bd import BdStore  # noqa: E402
from taskloop_dash import bind, serve  # noqa: E402
from taskloop_dash.app import Dash  # noqa: E402
from taskloop_dash.env import Env, Ports  # noqa: E402

try:
    import engine
    import reflect_digest
    import tl
except ImportError:  # a copy of dash/ with no engine beside it (a test of the bind rules): the ports then say nothing
    engine = reflect_digest = tl = None

plan, is_dev_checkout = bind.plan, bind.is_dev_checkout


def code_version():
    h = hashlib.sha256()
    for p in sorted(HERE.glob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def quiet(fn, default):
    """A port that never raises: tl.bd exits when bd is not on PATH."""
    def call(*a):
        try:
            return fn(*a)
        except (Exception, SystemExit):
            return default
    return call


def bd(repo, *args, timeout=30):
    """The dashboard's bd: the engine's adapter (--actor, --json), one process site."""
    if not shutil.which("bd"):
        raise OSError(2, "bd is not installed")
    r = BdStore("tl-dash", repo, timeout=timeout).passthrough(list(args))
    if r.code == 127:  # the adapter folds "bd cannot be run" into 127
        raise OSError(2, "bd cannot be run")
    return types.SimpleNamespace(returncode=r.code, stdout=r.out, stderr=r.err)


def ports():
    return Ports(bd=bd, slot_beads=quiet(lambda repo: [engine.dataclasses.asdict(b) for b in tl.slot_beads(repo)], []), waiting_line=quiet(lambda repo: tl.waiting_line(repo), []),
                 load_cfg=quiet(lambda repo: engine.dataclasses.asdict(engine.load_cfg(repo)), {"pick_label": "auto", "skip_labels": []}),
                 reflections=quiet(lambda hours: reflect_digest.view(hours), {}),
                 installed_versions=quiet(lambda: sorted(tl.cache_dirs("task-loop")), []))


def make_dash():
    return Dash(Env(ports=ports(), version=code_version()))


def inbox():
    return make_dash().asks.inbox()


def answer(body):
    return make_dash().asks.answer(body)


def withdraw(body):
    return make_dash().asks.withdraw(body)


def main():
    serve.main(Env(ports=ports(), version=code_version()), HERE, page=HERE / "index.html")


if __name__ == "__main__":
    main()
