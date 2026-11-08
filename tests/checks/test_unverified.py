"""A check that exits UNVERIFIED_EXIT is unverified: never passed, never cached as a pass, and the land refuses on it."""
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.check_host import CheckHostCase
from support.fakegit import FakeGit
from support.narrow_hosts import Stopped
from support.narrow_land import table_kit

from tltestkit import procsim
from tltestkit.checks import res
from tltestkit.narrow import must

# isort: split
from support.memstores import fake_stores
from support.spawn import port_git

from tlgate import evidence
from tlgate.cache import InputKeys, RunMemo, key_digest
from tlkernel.bead import Bead
from tlkernel.checkenums import CheckStatus
from tlkernel.checks import UNVERIFIED_EXIT, Check, CheckResult, CheckRun, PassRecord, verdict_of
from tlkernel.ids import BeadId, CheckId, TreeSha
from tlkernel.runkey import BaseSha
from tlland import gate


def unverified(id="render") -> CheckResult:
    return CheckResult(id=CheckId(id), cmd=id, group="tests", exit=UNVERIFIED_EXIT, status="unverified")


class Recorded(CheckHostCase):
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
        assert (first[0].status, first[0].exit, first[0].word) == ("unverified", UNVERIFIED_EXIT, CheckStatus.UNVERIFIED)
        assert count.read_text() == "xx"  # not retried within a round, not served from the cache in the next
        assert not again[0].cached
        assert [[c.id for c in group] for group in (first.passed, first.failed, first.unverified)] == [[], [], ["render"]]

    def test_the_verdict_is_closed(self):
        assert [verdict_of(0), verdict_of(1), verdict_of(UNVERIFIED_EXIT), verdict_of(124)] == ["passed", "failed", "unverified", "failed"]

    def test_the_round_text_marks_it_apart(self):
        text = "\n".join(evidence.round_lines([unverified(), res("ok", 0)]))
        assert "? [tests] `render` exit 86 (unverified" in text
        run = CheckRun(round=1, results=[unverified(), res("ok", 0)])
        assert "1 passed, 1 unverified: render" in evidence.round_outcome(run)


class Cache(Case):
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
        assert seeded.hit(seeded.key(c)) is None
        fresh = self.memo()
        key = must(fresh.key(c))
        fresh.remember(key, unverified(), 1, "/log")
        assert fresh.hit(key) is None
        fresh.remember(key, res("render", 0), 1, "/log")
        assert fresh.hit(key) is not None
        assert fresh.has(c)


class Land(Case):
    def lander(self, run):
        git = FakeGit(merge_base="base")
        git.tree_of = Mock(return_value="tree")
        git.diff_entries = Mock(return_value=[])
        return table_kit(git, last_run=run).lander

    def test_the_land_refuses_on_an_unverified_check_and_names_it(self):
        with pytest.raises(Stopped) as cm:
            self.lander(CheckRun(round=1, results=[res("ok", 0), unverified("render-evidence")])).finish(
                Bead(id=BeadId("t-1"), title="t", status="open"))
        assert "`render-evidence` is unverified" in cm.value.why
        assert cm.value.kind == "FAULT_LAND"

    def test_nothing_unverified_is_no_refusal(self):
        assert gate.refusal(CheckRun(round=1, results=[res("ok", 0)])) == ""
        assert not gate.deferred(unverified())
