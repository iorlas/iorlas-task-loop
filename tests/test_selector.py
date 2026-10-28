"""engine.selector (tl-7y6.7.18) and engine.selector_shadow (tl-7y6.7.21)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_engine as te  # noqa: E402
from test_engine import PY  # noqa: E402
from checks import selector as sel  # noqa: E402

ST = {"checks": [], "files": []}


class SelectorTest(unittest.TestCase):
    setUp = te.EngineTest.setUp
    tearDown = te.EngineTest.tearDown
    fake_bd = te.EngineTest.fake_bd
    commit_base_cfg = te.EngineTest.commit_base_cfg
    run_engine = te.EngineTest.run_engine
    checks_engine = te.EngineTest.checks_engine

    def selector(self, out, code=0):
        """A selector command that prints `out` (a dict or raw text) and exits `code`."""
        f = Path(self.tmp.name) / "sel.py"
        f.write_text("import sys\nprint(%r)\nsys.exit(%d)\n" % (out if isinstance(out, str) else json.dumps(out), code))
        return '%s "%s"' % (PY, f)

    def marks(self):
        a, b = (Path(self.tmp.name) / n for n in ("a", "b"))
        mk = lambda p, rc: PY + ' -c "open(%r, \'a\').write(\'1\'); raise SystemExit(%d)"' % (str(p), rc)
        return a, b, mk

    def records(self, eng, kind):
        return [json.loads(l) for l in eng.log_path.read_text().splitlines() if '"kind": "%s"' % kind in l]


class Hook(SelectorTest):
    def test_absent_selector_runs_every_check_and_writes_no_record(self):
        a, b, mk = self.marks()
        eng = self.checks_engine(checks=[{"id": "a", "cmd": mk(a, 0)}, {"id": "b", "cmd": mk(b, 0)}])
        res = eng.run_checks(ST, "s")
        self.assertEqual([c["status"] for c in res], ["ran", "ran"])
        self.assertEqual(self.records(eng, "selector"), [])

    def test_a_skipped_check_is_stored_skipped_selector_never_passed(self):
        a, b, mk = self.marks()
        eng = self.checks_engine(checks=[{"id": "a", "cmd": mk(a, 0)}, {"id": "b", "cmd": mk(b, 0)}],
                                 selector=self.selector({"checks": ["a"], "hatch": None, "reason": "only a"}))
        res = {c["id"]: c for c in eng.run_checks(ST, "s")}
        self.assertEqual((res["a"]["status"], res["b"]["status"], res["b"]["why"]), ("ran", "skipped", "selector"))
        self.assertFalse(b.exists())
        rec = self.records(eng, "selector")[0]
        self.assertEqual((rec["selected"], rec["skipped"], rec["hatch_reason"], rec["stage"]), (["a"], ["b"], "", "write"))

    def test_a_hatch_escalates_to_the_full_set(self):
        a, b, mk = self.marks()
        eng = self.checks_engine(checks=[{"id": "a", "cmd": mk(a, 0)}, {"id": "b", "cmd": mk(b, 0)}],
                                 selector=self.selector({"checks": ["a"], "hatch": "pyproject changed", "reason": "x"}))
        res = eng.run_checks(ST, "s")
        self.assertEqual([c["status"] for c in res], ["ran", "ran"])
        rec = self.records(eng, "selector")[0]
        self.assertEqual((rec["skipped"], rec["hatch_reason"]), ([], "pyproject changed"))

    def test_a_failing_or_unparseable_selector_means_the_full_set_and_a_warning(self):
        for out, code in (({"checks": []}, 3), ("not json", 0), ({"checks": "a"}, 0)):
            a, b, mk = self.marks()
            eng = self.checks_engine(checks=[{"id": "a", "cmd": mk(a, 0)}, {"id": "b", "cmd": mk(b, 0)}],
                                     selector=self.selector(out, code))
            res = eng.run_checks(ST, "s")
            self.assertEqual([c["status"] for c in res], ["ran", "ran"], out)
            self.assertTrue(self.records(eng, "selector")[0]["warning"], out)

    def test_stage_checks_always_run_and_a_fix_round_gets_since_and_the_red(self):
        a, b, mk = self.marks()
        seen = Path(self.tmp.name) / "seen"
        f = Path(self.tmp.name) / "sel.py"
        f.write_text("import os, json\nopen(%r, 'a').write(os.environ['TL_SELECT_STAGE'] + ':' + os.environ['TL_SELECT_SINCE'] + '\\n')\n"
                     "print(json.dumps({'checks': [], 'hatch': None, 'reason': ''}))\n" % str(seen))
        eng = self.checks_engine(checks=[{"id": "a", "cmd": mk(a, 1)}, {"id": "b", "cmd": mk(b, 0)}], selector='%s "%s"' % (PY, f))
        eng.run_checks({"checks": [PY + ' -c "pass"'], "files": []}, "s")  # round 1: nothing selected, the stage check runs
        self.assertFalse(a.exists())
        eng.green_tree, eng.red_ids = "treeX", ("a",)
        res = {c["id"]: c for c in eng.run_checks(ST, "fix", kind="fix")}
        self.assertEqual((res["a"]["status"], res["b"]["status"]), ("failed", "skipped"))  # the red one stays in
        self.assertEqual(seen.read_text().splitlines(), ["write:", "fix:treeX"])


class Shadow(SelectorTest):
    def test_shadow_records_a_miss_and_changes_no_outcome(self):
        a, b, mk = self.marks()
        checks = [{"id": "a", "cmd": mk(a, 0), "cache": False}, {"id": "b", "cmd": mk(b, 1), "cache": False}]
        pick_a = self.selector({"checks": ["a"], "hatch": None, "reason": "r"})
        plain = self.checks_engine(checks=checks).run_checks(ST, "s")
        a.unlink()
        b.unlink()
        eng = self.checks_engine(checks=checks, selector=pick_a, selector_shadow=True)
        res = eng.run_checks(ST, "s")
        self.assertEqual([(c["id"], c["status"], c["exit"]) for c in res], [(c["id"], c["status"], c["exit"]) for c in plain])
        self.assertTrue(a.exists() and b.exists())  # the full set ran
        rec = self.records(eng, "selector_shadow")[0]
        self.assertEqual((rec["bead"], rec["would_skip"], rec["missed"], rec["selected"]), ("t-1", ["b"], ["b"], ["a"]))
        self.assertEqual(sorted(rec["full"]), ["a", "b"])

    def test_shadow_with_no_miss_records_an_empty_missed_list(self):
        a, b, mk = self.marks()
        eng = self.checks_engine(checks=[{"id": "a", "cmd": mk(a, 0)}, {"id": "b", "cmd": mk(b, 0)}],
                                 selector=self.selector({"checks": ["a"], "hatch": None, "reason": ""}), selector_shadow=True)
        eng.run_checks(ST, "s")
        rec = self.records(eng, "selector_shadow")[0]
        self.assertEqual((rec["would_skip"], rec["missed"]), (["b"], []))

    def test_pick_and_shadow_are_typed_records(self):
        s = sel.Selection(("a",), "", "r")
        p = sel.pick(["a", "b"], s, "write")
        self.assertEqual((p.selected, p.skipped), (("a",), ("b",)))
        d = sel.shadow("t-1", "write", p, [{"id": "b", "status": "failed"}])
        self.assertEqual(d.missed, ("b",))


if __name__ == "__main__":
    unittest.main()
