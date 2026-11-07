"""The land's decisions, with git answered from a table (tests/support/fakegit.py): no repository, no process."""

import pytest
from support.fakegit import FakeGit
from support.narrow_hosts import FakeLandedHost, FakeLandRebaseHost, Stopped

from tltestkit.case import Case

# isort: split
from taskloop.app.land.push import Landed
from taskloop.app.land.rebase import LandRebase
from tlkernel.landmatchers import Push


def rebase(git: FakeGit) -> LandRebase:
    """The land's rebase over a host with just what it reads (support/narrow_hosts.py FakeLandRebaseHost)."""
    return LandRebase(FakeLandRebaseHost(git, git.sh))


def landed(git: FakeGit) -> Landed:
    return Landed(FakeLandedHost(git, git.sh))


class Rebase(Case):
    def test_a_clean_rebase_has_no_problem(self):
        g = FakeGit(rebase=(0, ""))
        assert rebase(g).run(0, "") is None

    def test_a_conflict_is_a_problem_for_a_fix_round_naming_the_files(self):
        g = FakeGit(rebase=(1, "CONFLICT"), unmerged="a.txt\nb.txt")
        problem = rebase(g).run(0, "")
        assert problem is not None
        assert problem.kind == "conflict"
        assert "a.txt, b.txt" in problem.text

    def test_a_failed_rebase_with_no_conflict_aborts_and_stops_the_run(self):
        g = FakeGit(rebase=[(1, "boom"), (0, "")], unmerged="")
        with pytest.raises(Stopped) as cm:
            rebase(g).run(0, "")
        assert cm.value.kind == "FAULT_LAND"
        assert g.ran("rebase_abort")

    def test_a_failed_fetch_goes_to_the_same_branches_without_rebasing(self):
        g = FakeGit(unmerged="", rebase=(0, ""))
        with pytest.raises(Stopped):
            rebase(g).run(1, "no route to host")
        assert not g.ran("rebase")


class Already(Case):
    def test_a_tip_titled_after_the_bead_and_on_the_base_is_already_landed(self):
        g = FakeGit(log=("abc123", "Do the thing (t-1)"), is_ancestor=True)
        assert landed(g).already(fetch=False) == "abc123"

    def test_another_beads_tip_is_not(self):
        g = FakeGit(log=("abc123", "Do the thing (t-2)"))
        assert landed(g).already(fetch=False) == ""

    def test_a_tip_not_on_the_base_is_not(self):
        g = FakeGit(log=("abc123", "Do the thing (t-1)"), is_ancestor=False)
        assert landed(g).already(fetch=False) == ""


class Pushes(Case):
    def test_only_moved_ref_rejections_are_retryable(self):
        for reason in ("fetch first", "non-fast-forward", "stale info"):
            assert Push.rejected(f" ! [rejected] HEAD -> main ({reason})")
        for text in ("pre-push: rejected; fetch first", " ! [remote rejected] main (non-fast-forward)",
                     " ! [rejected] main (other policy)", "fatal: unable to access origin"):
            assert not Push.rejected(text)

    def test_what_the_network_killed_is_told_from_what_the_hooks_said(self):
        assert Push.transient("fatal: unable to access: curl 56 Recv failure")
        assert not Push.transient("pre-push hook: 3 tests failed\n" + "ok\n" * 400)
        assert Push.rejected(" ! [rejected] main -> main (fetch first)")
