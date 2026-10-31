"""A check that exits UNVERIFIED_EXIT is unverified: never passed, never cached as a pass, and the land refuses on it."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import procsim
from support.checks import res
from support.engine_case import EngineTest
from support.fakegit import FakeGit
from support.narrow import must
from support.narrow_hosts import Stopped, table_kit

# isort: split
from support.spawn import port_git

from taskloop.app.checks import evidence
from taskloop.app.checks.cache import InputKeys, RunMemo, key_digest
from taskloop.app.land import verified
from taskloop.contracts.bead import Bead
from taskloop.contracts.checks import UNVERIFIED_EXIT, Check, CheckResult, CheckRun, PassRecord, verdict_of
from taskloop.contracts.enums import CheckStatus
from taskloop.contracts.ids import BeadId, CheckId, TreeSha
from taskloop.contracts.runkey import BaseSha
from taskloop.stores.memory import fake_stores


def unverified(id="render") -> CheckResult:
    return CheckResult(id=CheckId(id), cmd=id, group="tests", exit=UNVERIFIED_EXIT, status="unverified")


class Recorded(EngineTest):
    def test_a_check_exiting_with_the_code_is_unverified_not_passed(self):
        count = Path(self.tmp.name) / "count"

        def run(cwd, env):
            count.write_text(count.read_text() + "x" if count.exists() else "x")
            return UNVERIFIED_EXIT, "no GPU on this host"
        cmd = procsim.fake("render", run)
        eng = self.checks_engine(checks=[{"id": "render", "cmd": cmd, "group": "tests", "retry": 3}])
        st = {"checks": [], "files": []}
        first = eng.run_checks(st, "s")
        again = eng.run_checks(st, "s")
        self.assertEqual((first[0].status, first[0].exit, first[0].word), ("unverified", UNVERIFIED_EXIT, CheckStatus.UNVERIFIED))
        self.assertEqual(count.read_text(), "xx")  # not retried within a round, not served from the cache in the next
        self.assertFalse(again[0].cached)
        self.assertEqual([[c.id for c in group] for group in (first.passed, first.failed, first.unverified)], [[], [], ["render"]])

    def test_the_verdict_is_closed(self):
        self.assertEqual([verdict_of(0), verdict_of(1), verdict_of(UNVERIFIED_EXIT), verdict_of(124)],
                         ["passed", "failed", "unverified", "failed"])

    def test_the_round_text_marks_it_apart(self):
        text = "\n".join(evidence.round_lines([unverified(), res("ok", 0)]))
        self.assertIn("? [tests] `render` exit 86 (unverified", text)
        run = CheckRun(round=1, results=[unverified(), res("ok", 0)])
        self.assertIn("1 passed, 1 unverified: render", evidence.round_outcome(run))


class Cache(unittest.TestCase):
    def memo(self, seed=None):
        stores, keys = fake_stores(), InputKeys(port_git(), "/nonexistent", TreeSha("t"))
        keys.files = {}  # the tree has no pin files (and git is not asked)
        memo = RunMemo(stores, "repo", keys, BaseSha("b"), {})
        if seed:
            key = must(memo.key(seed[0]))  # written by hand: remember() refuses what is not a pass
            stores.results("repo", key.check).of(key_digest(key)).write(
                PassRecord(key=key, result=seed[1], tree=TreeSha("t"), base=BaseSha("b"), round=1))
        return memo

    def test_a_cached_unverified_result_is_never_reused_as_a_pass(self):
        c = Check(id=CheckId("render"), cmd="render")
        seeded = self.memo((c, unverified()))
        self.assertIsNone(seeded.hit(seeded.key(c)))
        fresh = self.memo()
        key = must(fresh.key(c))
        fresh.remember(key, unverified(), 1, "/log")
        self.assertIsNone(fresh.hit(key))
        fresh.remember(key, res("render", 0), 1, "/log")
        self.assertIsNotNone(fresh.hit(key))
        self.assertTrue(fresh.has(c))


class Land(unittest.TestCase):
    def lander(self, run):
        return table_kit(FakeGit(), last_run=run).lander

    def test_the_land_refuses_on_an_unverified_check_and_names_it(self):
        with self.assertRaises(Stopped) as cm:
            self.lander(CheckRun(round=1, results=[res("ok", 0), unverified("render-evidence")])).finish(
                Bead(id=BeadId("t-1"), title="t", status="open"))
        self.assertIn("`render-evidence` is unverified", cm.exception.why)
        self.assertEqual(cm.exception.kind, "FAULT_LAND")

    def test_nothing_unverified_is_no_refusal(self):
        self.assertEqual(verified.refusal(CheckRun(round=1, results=[res("ok", 0)])), "")
        self.assertFalse(verified.deferred(unverified()))


if __name__ == "__main__":
    unittest.main()
