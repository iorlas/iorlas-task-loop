"""RunKey (tl-3u6.3): one memo of check runs, keyed by (check, tree, base, inputs, env). The land gate asks it, a changed env misses it,
and what git cannot see is never served from it (tl-bxk.8.19, tl-7y6.7.11)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import engine_case as te
from support import procsim
from support.checks import ck
from support.engine_case import CLEAN, PLAN, WRITE
from support.logs import records
from support.narrow import must

# isort: split
from taskloop.app.checks.cache import InputKeys, RunMemo
from taskloop.contracts import paths
from taskloop.contracts.checks import Check, CheckCacheEntry
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.runkey import BaseSha
from taskloop.stores.memory import MemDoc
from taskloop.stores.real import real_stores

ANSWERS = {"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}
ST = {"checks": [], "files": []}


def memo(env=None, doc=None, tree="t", base="b"):
    return RunMemo(doc or MemDoc(CheckCacheEntry), InputKeys("/nonexistent", TreeSha(tree), {}), BaseSha(base), env or {})


class Gate(te.EngineTest):
    def stage_then_gate(self, **extra):
        n = Path(self.tmp.name) / "runs"
        both = procsim.fake("both", procsim.appends(n))
        rc, _ = self.run_engine(ANSWERS, checks=[{"id": "ut", "cmd": both, "run": "both", **extra}])
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(n.read_text(), "1")  # the stage ran it; the gate on the same key did not
        self.assertTrue(records(self.eng, "gate_end")[-1]["skipped"])

    def test_the_land_gate_never_reruns_a_whole_tree_check_a_stage_ran_green(self):
        self.stage_then_gate()

    def test_the_land_gate_never_reruns_a_check_with_inputs_a_stage_ran_green(self):
        self.stage_then_gate(inputs=["f.txt"])

    def test_the_land_gate_never_reruns_a_check_with_an_env_a_stage_ran_green(self):
        self.stage_then_gate(env={"A": "1"})

    def test_gate_green_is_every_key_in_the_memo(self):
        n = Path(self.tmp.name) / "runs"
        eng = self.checks_engine(checks=[{"id": "g", "cmd": procsim.fake("g", procsim.appends(n)), "run": "both"}])
        self.assertFalse(eng.checker.gate_green())
        eng.run_checks(ST, "s")
        self.assertTrue(eng.checker.gate_green())
        (self.wt / "new.txt").write_text("x")  # another tree: another key
        self.assertFalse(eng.checker.gate_green())


class Env(te.EngineTest):
    def test_a_changed_check_env_misses_the_memo_even_without_inputs(self):
        n = Path(self.tmp.name) / "runs"
        cmd = procsim.fake("e", procsim.appends(n))
        self.checks_engine(checks=[{"id": "e", "cmd": cmd}]).run_checks(ST, "s")
        self.checks_engine(checks=[{"id": "e", "cmd": cmd}]).run_checks(ST, "s")
        self.assertEqual(n.read_text(), "1")
        self.checks_engine(checks=[{"id": "e", "cmd": cmd, "env": {"A": "1"}}]).run_checks(ST, "s")
        self.assertEqual(n.read_text(), "11")

    def test_a_changed_engine_env_digest_misses(self):
        c = Check(id=CheckId("e"), cmd="e")
        a, b = memo({"TL_SLOT": "one"}), memo({"TL_SLOT": "two"})
        self.assertNotEqual(a.key(c), b.key(c))
        self.assertEqual(a.key(c), memo({"TL_SLOT": "one"}).key(c))
        self.assertNotEqual(a.key(c), a.key(c.replace(env={"A": "1"})))
        a.remember(must(a.key(c)), te.res("e", 0), 1, "/l")
        self.assertTrue(a.has(c))
        self.assertIsNone(a.hit(b.key(c)))

    def test_the_key_names_tree_base_and_command(self):
        c = Check(id=CheckId("e"), cmd="e")
        self.assertNotEqual(memo().key(c), memo(tree="t2").key(c))
        self.assertNotEqual(memo().key(c), memo(base="b2").key(c))
        self.assertNotEqual(memo().key(c), memo().key(c.replace(cmd="other")))
        self.assertEqual(memo().key(c), memo().key(c.replace(cmd="e  ")))


class MachineState(te.EngineTest):
    """tl-bxk.8.19: a check about a running editor or a log outside git was served by tree hash."""

    def test_a_check_that_may_not_be_cached_has_no_key_so_nothing_can_be_reused(self):
        c = Check(id=CheckId("editor"), cmd="! pgrep unity", cache=False)
        m = memo()
        self.assertIsNone(m.key(c))
        self.assertFalse(m.has(c))
        self.assertIsNone(m.hit(None))

    def test_a_plan_command_reading_an_untracked_file_reruns_after_the_file_changes(self):
        n = Path(self.tmp.name) / "runs"
        log = self.wt / "Editor.log"
        eng = self.checks_engine()
        st = {"checks": ck([procsim.fake("reads-log", procsim.appends(n))]), "files": []}
        log.write_text("closed\n")
        eng.run_checks(st, "s")
        log.write_text("open\n")
        eng.run_checks(st, "s")
        self.assertEqual(n.read_text(), "11")

    def test_a_ref_to_a_registered_check_is_not_a_second_run(self):
        c = Check(id=CheckId("e"), cmd="e")
        m = memo()
        m.remember(must(m.key(c)), te.res("e", 0), 1, "/l")
        self.assertEqual(m.command_key(c).check, "e")  # a command is its own identity inside a block


class OldFormat(unittest.TestCase):
    def test_a_cache_file_of_the_old_format_is_a_miss_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = paths.ConfigDir(Path(d))
            doc = real_stores(cfg).check_cache.of("b-1")
            path = cfg.check_cache("b-1")
            path.parent.mkdir(parents=True)
            path.write_text('{"v": 1, "key": "t b", "whole": {}, "inputs": {}, "base_red": {}}')
            self.assertIsNone(doc.read())
            m = RunMemo(doc, InputKeys("/nonexistent", TreeSha("t"), {}), BaseSha("b"), {})
            self.assertFalse(m.has(Check(id=CheckId("e"), cmd="e")))
            m.save()
            self.assertEqual(doc.read(), CheckCacheEntry())


if __name__ == "__main__":
    unittest.main()
