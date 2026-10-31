"""`tl green`: green only for a pass of that step on exactly that tree and base, read from the check memo; it writes nothing."""
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.cli import green
from taskloop.contracts.checks import CacheHit, CheckCacheEntry, CheckResult, RunEntry, Verdict
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.runkey import BaseSha, Digest, RunKey
from taskloop.stores.files import FileDocSet


def run(step="unit", tree="T1", base="B1", status: Verdict = "passed"):
    key = RunKey(check=CheckId(step), tree=TreeSha(tree), base=BaseSha(base), inputs=Digest("i"), env=Digest("e"))
    res = CheckResult(id=CheckId(step), cmd="x", group="g", exit=0 if status == "passed" else 1, status=status)
    return RunEntry(key=key, hit=CacheHit(result=res))


class GreenCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(self.tmp.name)
        self.out: list[str] = []

    def ask(self, step="unit", tree="T1", base="B1", bead="t-1"):
        a = Namespace(step=step, bead=bead, tree=tree, base=base)
        return green.cmd_green(a, self.cfg, self.out.append)

    def memo(self, *runs):
        FileDocSet(self.cfg.check_cache, CheckCacheEntry).of("t-1").write(CheckCacheEntry(runs=list(runs)))

    def test_no_memo_is_not_green(self):
        self.assertEqual(self.ask(), 1)
        self.assertEqual(self.out, ["not green: unit tree T1 base B1"])

    def test_pass_for_that_tree_and_base_is_green(self):
        self.memo(run())
        self.assertEqual(self.ask(), 0)
        self.assertEqual(self.out, ["green: unit tree T1 base B1"])

    def test_other_step_tree_base_or_bead_is_not_green(self):
        self.memo(run())
        self.assertEqual(self.ask(step="lint"), 1)
        self.assertEqual(self.ask(tree="T2"), 1)
        self.assertEqual(self.ask(base="B2"), 1)
        self.assertEqual(self.ask(bead="t-2"), 1)

    def test_a_remembered_non_pass_is_not_green(self):
        self.memo(run(status="failed"))
        self.assertEqual(self.ask(), 1)

    def test_asking_writes_nothing(self):
        self.memo(run())
        before = self.cfg.check_cache("t-1").read_bytes()
        self.ask()
        self.assertEqual(self.cfg.check_cache("t-1").read_bytes(), before)
        self.assertEqual(self.ask(bead="t-9"), 1)
        self.assertFalse(self.cfg.check_cache("t-9").exists())


if __name__ == "__main__":
    unittest.main()
