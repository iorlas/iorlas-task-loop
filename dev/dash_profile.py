"""Profile dashboard reads against the real config without opening dash.token.

Run: UV_OFFLINE=1 uv run python dev/dash_profile.py
Warm polls advance the clock four seconds; refresh includes waiting for background work.
The final row forces a full build after 121 seconds to expose stamp caching beyond the fallback TTLs.
"""

import argparse
import builtins
import cProfile
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import dash_profile_fixture

from taskloop.app.launch import dash_ports
from taskloop_dash.app import Dash
from taskloop_dash.env import Env
from taskloop_dash.index import Indexer, reindex
from taskloop_dash.views import snapshot as snapshots
from tlkernel.env import snapshot
from tlkernel.paths import ConfigDir, default_root


class CountedFile:
    def __init__(self, file, counts):
        self.file, self.counts = file, counts

    def __getattr__(self, name):
        return getattr(self.file, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return self.file.__exit__(*args)

    def read(self, *args):
        data = self.file.read(*args)
        self.counts["bytes"] += len(data)
        return data

    def readline(self, *args):
        data = self.file.readline(*args)
        self.counts["bytes"] += len(data)
        return data

    def __iter__(self):
        while line := self.readline():
            yield line


def instrument(stack, counts):
    original_open, original_popen = builtins.open, subprocess.Popen.__init__

    def opening(path, mode="r", *args, **kwargs):
        if isinstance(path, (str, Path)) and Path(path).name == "dash.token":
            raise PermissionError("profiler never opens dash.token")
        file = original_open(path, mode, *args, **kwargs)
        if "r" in mode:
            counts["opens"] += 1
            return CountedFile(file, counts)
        return file

    def spawning(self, *args, **kwargs):
        counts["processes"] += 1
        return original_popen(self, *args, **kwargs)

    def counted(fn, key):
        def call(*args, **kwargs):
            counts[key] += 1
            return fn(*args, **kwargs)
        return call

    for target in ("builtins.open", "io.open"):
        stack.enter_context(patch(target, opening))
    stack.enter_context(patch("subprocess.Popen.__init__", spawning))
    for name, key in (("stat", "stats"), ("fstat", "stats"), ("scandir", "dirlists"), ("listdir", "dirlists")):
        stack.enter_context(patch.object(os, name, counted(getattr(os, name), key)))


def measure(endpoint, state, call):
    counts = Counter()
    profiler = cProfile.Profile()
    with ExitStack() as stack:
        instrument(stack, counts)
        start = time.perf_counter()
        profiler.enable()
        result = call()
        profiler.disable()
        elapsed = (time.perf_counter() - start) * 1000
    views = sum(entry.inlinetime for entry in profiler.getstats() if not isinstance(entry.code, str)
                and "taskloop_dash/views" in entry.code.co_filename) * 1000
    print(f"| {endpoint} | {state} | {elapsed:.2f} | {counts['processes']} | {counts['opens']} | "
          f"{counts['bytes']} | {counts['stats']} | {counts['dirlists']} | {views:.2f} |", flush=True)
    return result


def profile(cfg, ports, fixture):
    """Index once, then measure a fresh process and ordinary polls independently."""
    offset = [0.0]
    env = Env(cfg.root, home=cfg.root, ports=ports, clock=lambda: time.time() + offset[0], version="profile")
    dash = Dash(env)
    print("| Endpoint | State | ms | Processes | Opens | Bytes | Stats | Dirlists | Views ms |")
    print("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    counts = measure("index", "from scratch", lambda: reindex(cfg, clock=env.clock))
    print(f"Indexed {counts['run']} runs and {counts['source']} sources.", flush=True)
    subprocess.run([sys.executable, __file__, "--cold", "--config", str(cfg.root), *(["--fixture"] if fixture else [])], check=True)
    with Indexer(cfg, clock=env.clock) as index:
        while not index.pass_once():
            pass
    measure("snapshot", "first in parent", dash.reads.snapshot)
    # Discover the drawer from the built world rather than creating another world.
    world, _ = dash.reads.built()
    pair = next(((p.id, b.id) for p in world.projects for b in p.beads if "slot" not in b.labels), None)
    endpoints: list[tuple[str, Callable[[], object]]] = [("snapshot", dash.reads.snapshot)]
    if pair:
        endpoints.append(("bead", lambda: dash.reads.bead(*pair)))
    for name, call in endpoints:
        if name != "snapshot":
            measure(name, "cold", call)
        offset[0] += 4
        with Indexer(cfg, clock=env.clock) as index:
            while not index.pass_once():
                pass
        measure(name, "warm poll", call)
        measure(name, "refresh drain", dash.reads.wait)
        measure(name, "hot", call)
    offset[0] += 121
    with Indexer(cfg, clock=env.clock) as index:
        while not index.pass_once():
            pass
    measure("snapshot", "full build +121s", lambda: snapshots.build(dash.reads.worlds.world()))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path)
    ap.add_argument("--fixture", action="store_true", help="171 generated runs inside .task/scratch; no host state")
    ap.add_argument("--cold", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    process = snapshot()
    ports = dash_profile_fixture.ports() if args.fixture else dash_ports.ports(process)
    cfg = ConfigDir(args.config or default_root(process))
    if args.cold:
        measure("snapshot", "cold process, indexed DB", Dash(Env(cfg.root, home=cfg.root, ports=ports)).reads.snapshot)
    elif args.fixture:
        scratch = Path(__file__).resolve().parents[1] / ".task" / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dash-profile-", dir=scratch) as folder:
            cfg = ConfigDir(folder)
            dash_profile_fixture.populate(cfg)
            profile(cfg, ports, True)
    else:
        profile(cfg, ports, False)


if __name__ == "__main__":
    main()
