"""What the loop tests ask of the loop's files and queue, through the same code the loop uses (loop_env, app/loop)."""
import dataclasses
import json
import os
import sys
from pathlib import Path

import support.paths  # noqa: F401  (ROOT/src on sys.path)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "task-loop"))
import loop_env  # noqa: E402
import tl  # noqa: E402
from taskloop.app.loop.queue import rank_ready  # noqa: E402
from taskloop.contracts.loop import LoopState  # noqa: E402


def fake_install(cache, ver, tl_py="import sys\n", missing=(), loop_py=""):
    """A version tree in the plugin cache: the core files of an install (loop_env.py holds `loop_py`), a plugin.json."""
    d = Path(cache) / ver / "skills" / "task-loop"
    d.mkdir(parents=True)
    (d.parents[1] / ".claude-plugin").mkdir()
    (d.parents[1] / ".claude-plugin" / "plugin.json").write_text("{}")
    for f in ("tl.py", "loop_env.py", "engine.py"):
        if f not in missing:
            (d / f).write_text(tl_py if f == "tl.py" else loop_py if f == "loop_env.py" else "")
    return d


def files(repo):
    return loop_env.files_of(repo)


def queue(repo, store=None, say=lambda _: None):
    """([(bead, reason)] in the order the loop takes them, [(id, why skipped)]): `tl next`'s own look."""
    env = loop_env.build(repo, store)
    env.fetch()
    q, _ = rank_ready(env, env.profile().engine, say)
    return [(r.bead, r.reason) for r in q.ranked], [(s.bead, s.skip.why) for s in q.skipped]


def log(repo):
    return loop_env.cfgdir().loop_log(tl.repo_key(repo))


def state_path(repo, pid):
    return loop_env.cfgdir().loop_state("%s.%d" % (tl.repo_key(repo), pid))


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
    return loop_env.cfgdir().loop_command(tl.repo_key(repo))


def rests(repo):
    return files(repo).rests()


def rest_file(repo):
    return loop_env.cfgdir().loop_rest(tl.repo_key(repo))


def last_exit(repo):
    return files(repo).last_exit()


def rows(repo):
    return [json.loads(x) for x in log(repo).read_text().splitlines()] if log(repo).exists() else []
