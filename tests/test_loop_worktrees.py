"""Two loops on one repo never share a worktree: the first takes its session's loop-<session>, every later one its own actor's."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from taskloop.app.loop.loop import Loop

REPO = "/w/repo"
SESSION = "tl-eaa4b1f2"


def wt(name: str) -> str:
    return f"{REPO}/.worktrees/loop-{name}"


class Fleet:
    """The loops of one repo on fake ports: each has an actor of its own under one session; the state files list the live ones."""

    def __init__(self) -> None:
        self.states: dict[int, str] = {}  # pid -> the worktree it published

    def start(self, pid: int, suffix: str) -> str:
        env = SimpleNamespace(session_actor=SESSION, actor=lambda: f"{SESSION}-{suffix}", pid=pid, repo=REPO)
        files = SimpleNamespace(live=lambda but=None: [SimpleNamespace(worktree=w) for p, w in self.states.items() if p != but])
        name = Loop.worktree_name(SimpleNamespace(env=env, files=files))  # type: ignore[arg-type]
        self.states[pid] = wt(name)
        return name


class TwoLoops(unittest.TestCase):
    def test_loops_of_one_session_on_one_repo_get_distinct_worktrees(self):
        fleet = Fleet()
        a, b, c = fleet.start(101, "fa5db6"), fleet.start(102, "09ac11"), fleet.start(103, "77e0d2")
        self.assertEqual(a, "eaa4b1f2")  # the first: its session's
        self.assertEqual((b, c), ("eaa4b1f2-09ac11", "eaa4b1f2-77e0d2"))  # then each its own actor's
        self.assertEqual(len({a, b, c}), 3)

    def test_a_restarted_loop_takes_its_session_worktree_back_once_the_other_is_gone(self):
        fleet = Fleet()
        fleet.start(101, "fa5db6")
        fleet.start(102, "09ac11")
        del fleet.states[101]  # the first died
        self.assertEqual(fleet.start(103, "77e0d2"), "eaa4b1f2")


if __name__ == "__main__":
    unittest.main()
