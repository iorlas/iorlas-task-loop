"""What the loop tests ask of the loop's files and queue, through the same code the loop uses (wloop, app/loop)."""
import dataclasses
import json
import os
from pathlib import Path

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from taskloop.app.launch import loop as wloop
from taskloop.app.loop.queue import rank_ready
from taskloop.app.wire import slots as wslots
from taskloop.contracts.loop import LoopState


def fake_install(cache, ver, tl_py="import sys\n", missing=(), loop_py=""):
    """A version tree in the plugin cache: the core file of an install (tl.py), the loop module (`loop_py`) and an empty engine module
    under src/, a plugin.json."""
    d = Path(cache) / ver / "skills" / "task-loop"
    d.mkdir(parents=True)
    (d.parents[1] / ".claude-plugin").mkdir()
    (d.parents[1] / ".claude-plugin" / "plugin.json").write_text("{}")
    if "tl.py" not in missing:
        (d / "tl.py").write_text(tl_py)
    app = d.parents[1] / "src" / "taskloop" / "app"  # the loop and engine modules the loop imports to vet an install
    for pkg in (app.parent, app, app / "run", app / "launch"):
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text("")
    (app / "run" / "engine.py").write_text("")
    (app / "launch" / "loop.py").write_text(loop_py)
    return d


def files(repo):
    return wloop.files_of(repo)


def queue(repo, store=None, say=lambda _: None):
    """([(bead, reason)] in the order the loop takes them, [(id, why skipped)]): `tl next`'s own look."""
    env = wloop.build(repo, store)
    env.fetch()
    q, _ = rank_ready(env, env.profile().engine, say)
    return [(r.bead, r.reason) for r in q.ranked], [(s.bead, s.skip.why) for s in q.skipped]


def log(repo):
    return wloop.cfgdir().loop_log(wslots.repo_key(repo))


def state_path(repo, pid):
    return wloop.cfgdir().loop_state(f"{wslots.repo_key(repo)}.{pid}")


def write_state(repo, pid=None, **fields):
    """A loop's state file as a LoopState (a live loop of a test: the test's own pid, or a child's)."""
    pid = pid or os.getpid()
    st = LoopState(pid=pid, started=fields.pop("started", 1.0), t=fields.pop("t", 1.0), repo=repo, version="0.0.1", code_dir="/x",
                   actor="tl-x")
    files(repo).write(dataclasses.replace(st, **fields))


def read_state(repo, pid=None):
    return files(repo).read(pid or os.getpid())


def live(repo):
    return files(repo).live()


def command(repo):
    return wloop.cfgdir().loop_command(wslots.repo_key(repo))


def rests(repo):
    return files(repo).rests()


def rest_file(repo):
    return wloop.cfgdir().loop_rest(wslots.repo_key(repo))


def last_exit(repo):
    return files(repo).last_exit()


def rows(repo):
    return [json.loads(x) for x in log(repo).read_text().splitlines()] if log(repo).exists() else []
