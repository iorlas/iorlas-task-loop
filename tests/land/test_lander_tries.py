"""The land's tries and its lock, with git answered from a table (tests/support/fakegit.py): no repository, no process.
What `git` itself does on a rebase or a push race stays in test_engine_land_1 and test_stages_land."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import FakeGit
from support.narrow_hosts import LandKit, Stopped, table_kit

# isort: split
from taskloop.app.land.gate import Problem, ProblemKind, mint
from taskloop.app.land.lander import Lander
from taskloop.app.land.state import Land, Phase
from taskloop.contracts import log as rec
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.runkey import BaseSha

REJECTED = (1, " ! [rejected]        HEAD -> main (fetch first)")
PUSHED = (0, "")


def land_with(git: FakeGit, **kw) -> tuple[Lander, LandKit]:
    """The lander (composed of real steps, each over its own small fake host: support/narrow_hosts.py LandKit) and that kit."""
    kit = table_kit(git, **kw)
    return kit.lander, kit


def tries_of(kit: LandKit) -> list[rec.LandTry]:
    return [r for r in kit.land.emitted() if isinstance(r, rec.LandTry)]


def repo(bases, heads, pushes) -> FakeGit:
    """Git as the land sees it: the base tip and the branch tip once before the rebase and once after, per try, then what each push said."""
    return FakeGit(**{"rev_parse__origin/main": list(bases), "rev_parse__HEAD": list(heads), "rev_parse__HEAD^{tree}": "tree",
                      "rev_parse__--verify__-q__HEAD": "", "rebase": (0, ""), "push": list(pushes)})


class Tries(unittest.TestCase):
    def test_when_main_moves_during_the_land_the_try_says_so_and_the_branch_moved_with_it(self):
        g = repo(["aaaa1111aaaa22", "bbbb3333bbbb44", "bbbb3333bbbb44", "bbbb3333bbbb44"], ["old", "new", "landed"], [PUSHED])
        lander, host = land_with(g)
        sha, problem = lander.tries(Land())
        self.assertEqual((sha, problem), ("landed", None))
        (got,) = tries_of(host)
        self.assertEqual(got, rec.LandTry(t=got.t, n=1, base_before="aaaa1111aaaa", base_after="bbbb3333bbbb",
                                           rebase_moved=True, failing=""))
        self.assertTrue(g.ran("rebase", "-q", "origin/main"))

    def test_when_main_stands_still_nothing_moved(self):
        g = repo(["aaa"] * 4, ["h", "h", "landed"], [PUSHED])
        lander, host = land_with(g)
        lander.tries(Land())
        (got,) = tries_of(host)
        self.assertEqual((got.base_before, got.base_after, got.rebase_moved), ("aaa", "aaa", False))


class PushedSha(unittest.TestCase):
    def test_the_push_names_the_sha_resolved_before_it_and_the_record_holds_that_sha_not_a_later_head(self):
        g = repo(["a"] * 4, ["h", "h", "pushed", "moved-after"], [PUSHED])
        lander, host = land_with(g)
        self.assertEqual(lander.tries(Land()), ("pushed", None))
        self.assertEqual(host.pushing.landed_sha, "pushed")
        self.assertNotIn("record pushed", host.events)  # the push is not an effect: what follows it is a plan, applied by synced
        self.assertTrue(g.ran("push", "--no-verify", "-q", "origin", "pushed:main"))
        lander.synced("pushed")
        self.assertEqual(host.events, ["record pushed", "sync"])

    def test_a_kill_after_the_landed_fact_resumes_at_bd_sync_and_records_nothing_twice(self):
        g = repo(["a"] * 4, ["h", "h", "pushed", "moved-after"], [PUSHED])
        lander, host = land_with(g)
        host.bd.fail = True  # bd's Dolt push cannot be reached: the first call stops the land after RecordLand
        with self.assertRaises(Stopped):
            lander.synced("pushed")
        host.bd.fail = False
        lander.synced("pushed")  # the same run again: the keys in the checkpoint say what is done
        self.assertEqual(host.events.count("record pushed"), 1)
        self.assertEqual(host.events.count("sync"), 1)


class Pushing(unittest.TestCase):
    def test_a_network_error_on_the_push_rests_the_land_instead_of_failing_it(self):
        g = repo(["a"] * 4, ["h", "h", "h"], [(128, "fatal: unable to access 'x': Could not resolve host")])
        lander, _ = land_with(g, up=False)
        st = Land()
        self.assertEqual(lander.tries(st), ("", None))
        self.assertIs(st.phase, Phase.NET_DOWN)

    def test_a_push_the_network_did_not_kill_is_a_fault_not_a_retry(self):
        g = repo(["a"] * 4, ["h", "h", "h"], [(1, "pre-push hook: 3 tests failed")])
        lander, _ = land_with(g)
        with self.assertRaises(Stopped) as cm:
            lander.tries(Land())
        self.assertEqual(cm.exception.kind, "FAULT_LAND")

    def test_a_network_error_while_the_network_looks_up_three_times_pauses_the_task(self):
        g = repo(["a"] * 4, ["h", "h", "h"], [(128, "fatal: unable to access 'x': Could not resolve host")])
        lander, _ = land_with(g, up=True)
        with self.assertRaises(Stopped) as cm:
            lander.tries(Land(flaky=2))
        self.assertEqual(cm.exception.kind, "PAUSE_NETWORK")


class Passes(unittest.TestCase):
    """The push takes a GatePass(tree, base) and checks it against the tree and base it is about to push."""

    def test_a_pass_for_another_tree_is_refused_as_stale_and_nothing_is_pushed(self):
        g = repo(["a"], ["h"], [PUSHED])
        _, host = land_with(g)
        got = host.pusher.push(Land(), mint(TreeSha("other"), BaseSha("a")))
        assert isinstance(got, Problem)
        self.assertEqual(got.kind, ProblemKind.STALE)
        self.assertFalse(g.ran("push"))
        self.assertEqual(host.pushing.landed_sha, "")

    def test_a_pass_made_before_the_base_moved_is_refused_as_stale_and_nothing_is_pushed(self):
        g = repo(["b"], ["h"], [PUSHED])
        _, host = land_with(g)
        got = host.pusher.push(Land(), mint(TreeSha("tree"), BaseSha("a")))
        assert isinstance(got, Problem)
        self.assertEqual(got.kind, ProblemKind.STALE)
        self.assertFalse(g.ran("push"))

    def test_a_pass_for_this_tree_and_base_pushes(self):
        g = repo(["a"], ["pushed"], [PUSHED])
        _, host = land_with(g)
        self.assertEqual(host.pusher.push(Land(), mint(TreeSha("tree"), BaseSha("a"))), "pushed")

    def test_a_pass_gone_stale_before_the_push_lets_the_lock_go_and_counts_as_main_moving(self):
        g = repo(["a", "a", "a", "b"], ["h", "h"], [PUSHED])
        lander, _ = land_with(g)
        st = Land()
        sha, problem = lander.tries(st)  # the pass is made on base a; the base read at the push is b
        self.assertEqual((sha, problem.kind if problem else None, st.moved), ("", ProblemKind.STALE, 1))
        self.assertFalse(g.ran("push"))


class Lock(unittest.TestCase):
    def test_a_push_rejected_twice_is_tried_again_in_one_lock_and_lands(self):
        g = repo(["a"] * 12, ["h"] * 8 + ["landed"], [REJECTED, REJECTED, PUSHED])
        lander, host = land_with(g)
        self.assertEqual(lander.land(), "landed")
        self.assertEqual(host.events, ["enter", "checks", "checks", "exit"])
        self.assertEqual([e.n for e in tries_of(host)], [1, 2, 3])
        self.assertEqual(sum(1 for c in g.calls if c[0] == "push"), 3)

    def test_a_push_rejected_three_times_stops_in_one_lock(self):
        g = repo(["a"] * 12, ["h"] * 9, [REJECTED] * 3)
        lander, host = land_with(g)
        with self.assertRaises(Stopped) as cm:
            lander.land()
        self.assertEqual((cm.exception.kind, host.events), ("FAULT_LAND", ["enter", "checks", "checks", "exit"]))
        self.assertIn("land rejected 3 times", cm.exception.why)
        self.assertFalse(host.pushing.landed_sha)


if __name__ == "__main__":
    unittest.main()
