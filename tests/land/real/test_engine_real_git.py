"""The engine's land on a real git repo: the integration set. Every other engine test runs on the gitsim (tests/support/gitsim); these
cells re-run a handful of land tests against real git (origin + clone), where git's own behaviour is what the test is about, so the sim
is checked against it. The stop-during-the-push test lives in test_engine_signals (its land command is a child
process that runs git push itself)."""
import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support.engine_case import real_git

# isort: split
from land import test_engine_land_1 as base

LIMIT_S = 30  # each cell is a whole engine run on real git (clone, rebase, push); 18.6 s of CPU was measured on a loaded host (wall 62 s)

CELLS = {
    "test_happy_path_lands_and_closes": "a land to a real origin: the pushed tree and the clone's origin/main are git's own",
    "test_wip_from_an_earlier_run_lands_as_one_titled_commit": "real commits and a real log: one titled commit reaches origin/main",
    "test_a_rebase_conflict_goes_to_a_fix_round_not_blocked": "git's own rebase conflict (markers, --continue) and the shell git grep",
    "test_a_conflict_fix_leaving_markers_is_not_accepted_the_marker_check_still_runs": "the marker check is a bash git grep, real index",
    "test_push_race_retry_keeps_one_land_lock_and_lands": "a push real git rejects because main moved, then the retry",
}


def cell(name: str, reason: str):
    fn = getattr(base.EngineLand1Test, name)

    @functools.wraps(fn)
    def run(self):
        return fn(self)

    return real_git(reason)(run)


class RealGitLandTest(base.EngineLand1Test):
    pass


for _name in dir(base.EngineLand1Test):
    if _name.startswith("test_"):
        setattr(RealGitLandTest, _name, cell(_name, CELLS[_name]) if _name in CELLS else None)
