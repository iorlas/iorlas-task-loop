"""The land's decisions, with git answered from a table (tests/support/fakegit.py): no repository, no process."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402,F401
from support.fakegit import FakeGit  # noqa: E402
from taskloop.app.land.lander import Lander  # noqa: E402
from taskloop.domain.land.matchers import Push  # noqa: E402


class Stop(Exception):
    def __init__(self, why: str, kind: str) -> None:
        super().__init__(why)
        self.why, self.kind = why, kind


def lander(git: FakeGit, **host) -> Lander:
    steps = SimpleNamespace(outcome=lambda *a: host.setdefault("outcomes", []).append(a))
    e = SimpleNamespace(git=git.git, sh=git.sh, cfg=SimpleNamespace(base="origin/main"), bead="t-1", dry=False, steps=steps,
                        fetch=lambda: (0, ""), blocked_for=lambda why, kind, **kw: Stop(why, kind), **host)
    return Lander(e)


class Rebase(unittest.TestCase):
    def test_a_clean_rebase_has_no_problem(self):
        g = FakeGit(rebase=(0, ""))
        self.assertIsNone(lander(g).rebase(0, ""))

    def test_a_conflict_is_a_problem_for_a_fix_round_naming_the_files(self):
        g = FakeGit(rebase=(1, "CONFLICT"), diff="a.txt\nb.txt")
        problem = lander(g).rebase(0, "")
        assert problem is not None
        self.assertEqual(problem.kind, "conflict")
        self.assertIn("a.txt, b.txt", problem.text)

    def test_a_failed_rebase_with_no_conflict_aborts_and_stops_the_run(self):
        g = FakeGit(rebase=[(1, "boom"), (0, "")], diff="")
        with self.assertRaises(Stop) as cm:
            lander(g).rebase(0, "")
        self.assertEqual(cm.exception.kind, "FAULT_LAND")
        self.assertTrue(g.ran("rebase", "--abort"))

    def test_a_failed_fetch_goes_to_the_same_branches_without_rebasing(self):
        g = FakeGit(diff="", rebase=(0, ""))
        with self.assertRaises(Stop):
            lander(g).rebase(1, "no route to host")
        self.assertFalse(g.ran("rebase", "-q"))


class Already(unittest.TestCase):
    def test_a_tip_titled_after_the_bead_and_on_the_base_is_already_landed(self):
        g = FakeGit(rev_parse="abc123", log="Do the thing (t-1)", merge_base=(0, ""))
        self.assertEqual(lander(g).already(fetch=False), "abc123")

    def test_another_beads_tip_is_not(self):
        g = FakeGit(rev_parse="abc123", log="Do the thing (t-2)")
        self.assertEqual(lander(g).already(fetch=False), "")

    def test_a_tip_not_on_the_base_is_not(self):
        g = FakeGit(rev_parse="abc123", log="Do the thing (t-1)", merge_base=(1, ""))
        self.assertEqual(lander(g).already(fetch=False), "")


class Pushes(unittest.TestCase):
    def test_what_the_network_killed_is_told_from_what_the_hooks_said(self):
        self.assertTrue(Push.transient("fatal: unable to access: curl 56 Recv failure"))
        self.assertFalse(Push.transient("pre-push hook: 3 tests failed\n" + "ok\n" * 400))
        self.assertTrue(Push.rejected(" ! [rejected] main -> main (fetch first)"))


if __name__ == "__main__":
    unittest.main()
