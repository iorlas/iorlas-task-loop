"""A check child starts under `nice -n 10`; a git or worker command does not."""
import threading
from types import SimpleNamespace

import support.paths  # noqa: F401

from taskloop.app.run.shell import Shell
from taskloop.contracts.env import Env


class Spawns:
    def __init__(self) -> None:
        self.argv: list[str] = []

    def stream(self, argv, **_kw):
        self.argv = argv
        return SimpleNamespace(timed_out=None, signal=None, returncode=0, secs=0.0, survivors=())


def shell(spawner: Spawns) -> Shell:
    host = SimpleNamespace(env=Env({"PATH": "/usr/bin"}), cfg=SimpleNamespace(check_scratch_home=False), bead_env={}, wt="/repo",
                           spawner=spawner, halt=threading.Event(), log=None, killed=False)
    return Shell(host)


def test_check_runs_under_nice():
    spawns = Spawns()
    shell(spawns).stream(["just", "test"], "/repo", None, False, [], 60.0, "m1", "check", 0.0, threading.Event())
    assert spawns.argv == ["nice", "-n", "10", "just", "test"]


def test_other_commands_do_not():
    spawns = Spawns()
    shell(spawns).stream(["git", "status"], "/repo", None, False, [], 60.0, "m1", "command", 0.0, threading.Event())
    assert spawns.argv == ["git", "status"]
