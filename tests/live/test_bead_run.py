"""Scenario 1: a bead goes plan, write, checks, review, land and push on a real git remote (a bare repo), with real git and a real check
process; the worker is the stub lane `tl selftest` uses (a route.py answer per node), never a model and never a real bd."""
import subprocess

from taskloop.adapters.git import RealGit
from taskloop.app.launch import selftest
from taskloop.contracts.env import snapshot


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_given_a_bead_on_a_real_remote_when_the_engine_runs_then_it_lands_and_pushes(world):
    # Given: a bare origin, a clone with one commit, an open bead that asks for f.txt
    wt = world / "wt"
    assert selftest.git_repo(world, wt, RealGit()) is None
    before = git(world / "o.git", "rev-parse", "main")
    # When: the engine runs the bead with the stub worker
    rc, bead = selftest.run_engine(world, wt, snapshot())
    # Then: the bead is closed and the remote's main holds the file the worker wrote, as a new commit
    assert (rc, bead.status) == (0, "closed")
    after = git(world / "o.git", "rev-parse", "main")
    assert after != before
    assert git(world / "o.git", "show", "main:f.txt") == "f"
    assert git(world / "o.git", "merge-base", "--is-ancestor", before, after) == ""
