"""Scenario 5: the real-process race (dev/race.py): two loops, a hand run, a hold and two releases at once on a fake repo, two seeds.
It sat outside every run, which is how a loop that started no bead (tl-4xo) and a stale area check (tl-na3) went unseen."""
import subprocess
from pathlib import Path

RACE = Path(__file__).resolve().parents[2] / "dev" / "race.py"


def test_given_two_loops_and_hand_runs_when_they_race_then_nothing_is_shared_that_a_lock_guards():
    # Given/When: dev/race.py runs seeds 1 and 2 (about 35 s each), its own isolated HOME, config dir, bd and repo
    r = subprocess.run(["uv", "run", "--script", str(RACE), "--seeds", "1-2"], capture_output=True, text=True, timeout=900, check=False)
    # Then: every seed passed (a failed seed prints RACE_SEED=n FAILED and the broken checks on stderr)
    assert r.returncode == 0, r.stdout + r.stderr[-6000:]
    assert "failed seeds: none" in r.stdout
