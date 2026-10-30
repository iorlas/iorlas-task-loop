"""What the loop tests ask of the loop's files and queue, through the same code the loop uses (wloop, app/loop)."""
import json
import os
from pathlib import Path

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import homes
from support.spawn import port_git, real_spawner
from support.who import who
from taskloop.app.launch import loop as wloop
from taskloop.app.loop.queue import rank_ready
from taskloop.app.wire import slots as wslots
from taskloop.contracts.env import snapshot
from taskloop.contracts.loop import LoopState


def fake_install(cache, ver, tl_py="import sys\n"):
    """A version tree in the plugin cache: tl.py and a plugin.json."""
    d = Path(cache) / ver / "skills" / "task-loop"
    d.mkdir(parents=True)
    (d.parents[1] / ".claude-plugin").mkdir()
    (d.parents[1] / ".claude-plugin" / "plugin.json").write_text("{}")
    (d / "tl.py").write_text(tl_py)
    return d


def files(repo):
    return wloop.files_of(repo, homes.cfg())


def queue(repo, store=None, say=lambda _: None):
    """([(bead, reason)] in the order the loop takes them, [(id, why skipped)]): `tl next`'s own look."""
    env = wloop.build(repo, store, env=snapshot(), spawner=real_spawner(), git=port_git(), who=who())
    env.fetch()
    q, _ = rank_ready(env, env.profile().engine, say)
    return [(r.bead, r.reason) for r in q.ranked], [(s.bead, s.skip.why) for s in q.skipped]


def log(repo):
    return homes.cfg().loop_log(wslots.repo_key(repo))


def state_path(repo, pid):
    return homes.cfg().loop_state(f"{wslots.repo_key(repo)}.{pid}")


def write_state(repo, pid=None, **fields):
    """A loop's state file as a LoopState (a live loop of a test: the test's own pid, or a child's)."""
    pid = pid or os.getpid()
    st = LoopState(pid=pid, started=fields.pop("started", 1.0), t=fields.pop("t", 1.0), repo=repo, version="0.0.1", code_dir="/x",
                   actor="tl-x")
    files(repo).write(st.replace(**fields))


def read_state(repo, pid=None):
    return files(repo).read(pid or os.getpid())


def live(repo):
    return files(repo).live()


def command(repo):
    return homes.cfg().loop_command(wslots.repo_key(repo))


def rests(repo):
    return files(repo).rests()


def rest_file(repo):
    return homes.cfg().loop_rest(wslots.repo_key(repo))


def last_exit(repo):
    return files(repo).last_exit()


def rows(repo):
    return [json.loads(x) for x in log(repo).read_text().splitlines()] if log(repo).exists() else []
