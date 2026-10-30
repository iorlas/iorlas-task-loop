"""The land's tries and its lock, with git answered from a table (tests/support/fakegit.py): no repository, no process.
What `git` itself does on a rebase or a push race stays in test_engine_land_1 and test_stages_land."""
import contextlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import FakeGit

from taskloop.app.land.lander import Land, Lander
from taskloop.contracts import fence
from taskloop.contracts import log as rec

REJECTED = (1, " ! [rejected]        HEAD -> main (fetch first)")
PUSHED = (0, "")


class Stop(Exception):
    def __init__(self, why: str, kind: str) -> None:
        super().__init__(why)
        self.why, self.kind = why, kind


class Host(SimpleNamespace):
    """What the lander reads off the engine, with every collaborator but git a recorder."""

    def __init__(self, git: FakeGit) -> None:
        self.events: list[str] = []
        self.emitted: list[Any] = []
        self.warnings: list[str] = []

        @contextlib.contextmanager
        def locked(*_):
            self.events.append("enter")
            try:
                yield
            finally:
                self.events.append("exit")

        @contextlib.contextmanager
        def stop_deferred():
            yield []
        super().__init__(
            git=git.git, sh=git.sh, cfg=SimpleNamespace(base="origin/main", gate_checks=[], land_optimistic_tries=2,
                                                         land=["git", "push", "-q", "origin", "HEAD:main"]),
            wt=Path("/nonexistent"), store=None, claim=fence.offline("t-1"),
            bead="t-1", dry=False, dry_run=False, landed_sha="", pending_land_validation="", fixes=0,
            steps=SimpleNamespace(begin=lambda *a, **k: None, outcome=lambda *a: None, move=lambda *a: None),
            newfiles=SimpleNamespace(quarantine_strays=lambda: None),
            checkout=SimpleNamespace(fetch=lambda: (0, "")),
            log=SimpleNamespace(emit=self.emitted.append, note=lambda *_: None),
            waits=SimpleNamespace(locked=locked), land_lock_path=lambda: "lock", stop_deferred=stop_deferred,
            record_land=lambda sha: self.events.append("record " + sha), warn=self.warnings.append,
            plan_data=None, cases=SimpleNamespace(case_checks=lambda: []), run_dir="run",
            checkpoints=SimpleNamespace(save=lambda **kw: None),
            last_run=None, stores=SimpleNamespace(check_run=lambda *a: SimpleNamespace(read=lambda: None)),
            stage_checks=SimpleNamespace(stoppable=lambda *a: self.events.append("checks") or SimpleNamespace(failed=[], unverified=[])),
            blocked_for=lambda why, kind, **kw: Stop(why, kind))


def land_with(git: FakeGit) -> tuple[Lander, Host]:
    host = Host(git)
    return Lander(host), host


def repo(bases, heads, pushes) -> FakeGit:
    """Git as the land sees it: the base tip and the branch tip once before the rebase and once after, per try, then what each push said."""
    return FakeGit(**{"rev_parse__origin/main": list(bases), "rev_parse__HEAD": list(heads), "rev_parse__HEAD^{tree}": "tree",
                      "rev_parse__--verify__-q__HEAD": "", "rebase": (0, ""), "push": list(pushes)})


class Tries(unittest.TestCase):
    def test_when_main_moves_during_the_land_the_try_says_so_and_the_branch_moved_with_it(self):
        g = repo(["aaaa1111aaaa22", "bbbb3333bbbb44"], ["old", "new", "landed"], [PUSHED])
        lander, host = land_with(g)
        sha, problem = lander.tries(Land())
        self.assertEqual((sha, problem), ("landed", None))
        (got,) = host.emitted
        self.assertEqual(got, rec.LandTry(n=1, base_before="aaaa1111aaaa", base_after="bbbb3333bbbb", rebase_moved=True, failing=""))
        self.assertTrue(g.ran("rebase", "-q", "origin/main"))

    def test_when_main_stands_still_nothing_moved(self):
        g = repo(["aaa", "aaa"], ["h", "h", "landed"], [PUSHED])
        lander, host = land_with(g)
        lander.tries(Land())
        (got,) = host.emitted
        self.assertEqual((got.base_before, got.base_after, got.rebase_moved), ("aaa", "aaa", False))


class PushedSha(unittest.TestCase):
    def test_the_push_names_the_sha_resolved_before_it_and_the_record_holds_that_sha_not_a_later_head(self):
        g = repo(["a", "a"], ["h", "h", "pushed", "moved-after"], [PUSHED])
        lander, host = land_with(g)
        self.assertEqual(lander.tries(Land()), ("pushed", None))
        self.assertIn("record pushed", host.events)
        self.assertTrue(g.ran("push", "--no-verify", "-q", "origin", "pushed:main"))


class Pushing(unittest.TestCase):
    def test_a_network_error_on_the_push_rests_the_land_instead_of_failing_it(self):
        g = repo(["a", "a"], ["h", "h", "h"], [(128, "fatal: unable to access 'x': Could not resolve host")])
        lander, host = land_with(g)
        host.worker = SimpleNamespace(acts=SimpleNamespace(net_up=lambda: False))
        st = Land()
        self.assertEqual(lander.tries(st), ("", None))
        self.assertTrue(st.net_failed)

    def test_a_push_the_network_did_not_kill_is_a_fault_not_a_retry(self):
        g = repo(["a", "a"], ["h", "h", "h"], [(1, "pre-push hook: 3 tests failed")])
        lander, _ = land_with(g)
        with self.assertRaises(Stop) as cm:
            lander.tries(Land())
        self.assertEqual(cm.exception.kind, "FAULT_LAND")

    def test_a_network_error_while_the_network_looks_up_three_times_pauses_the_task(self):
        g = repo(["a", "a"], ["h", "h", "h"], [(128, "fatal: unable to access 'x': Could not resolve host")])
        lander, host = land_with(g)
        host.worker = SimpleNamespace(acts=SimpleNamespace(net_up=lambda: True))
        with self.assertRaises(Stop) as cm:
            lander.tries(Land(flaky=2))
        self.assertEqual(cm.exception.kind, "PAUSE_NETWORK")


class Lock(unittest.TestCase):
    def test_a_push_rejected_twice_is_tried_again_in_one_lock_and_lands(self):
        g = repo(["a"] * 6, ["h"] * 8 + ["landed"], [REJECTED, REJECTED, PUSHED])
        lander, host = land_with(g)
        self.assertEqual(lander.land(), "landed")
        self.assertEqual(host.events, ["enter", "checks", "checks", "record landed", "exit"])
        self.assertEqual([e.n for e in host.emitted], [1, 2, 3])
        self.assertEqual(sum(1 for c in g.calls if c[0] == "push"), 3)

    def test_a_push_rejected_three_times_stops_in_one_lock(self):
        g = repo(["a"] * 6, ["h"] * 9, [REJECTED] * 3)
        lander, host = land_with(g)
        with self.assertRaises(Stop) as cm:
            lander.land()
        self.assertEqual((cm.exception.kind, host.events), ("FAULT_LAND", ["enter", "checks", "checks", "exit"]))
        self.assertIn("land rejected 3 times", cm.exception.why)
        self.assertFalse(host.landed_sha)


if __name__ == "__main__":
    unittest.main()
