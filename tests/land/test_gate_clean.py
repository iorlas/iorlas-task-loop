"""The land gate judges committed files, independently of the slot's ignored state."""
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import procsim
from support.engine_case import EngineTest

from taskloop.app.land.gate import Gate, GatePass, Problem, ProblemKind
from taskloop.app.run.blocked import Blocked
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ports import Ran
from taskloop.contracts.slots import SlotGitError
from taskloop.domain.checks.specs import gate_items


class CleanGate(EngineTest):
    def engine(self, command):
        eng = self.checks_engine(checks=[{"id": "evidence", "cmd": command, "run": "both"}])
        (self.wt / ".gitignore").write_text(".task/\nignored.txt\n")
        eng.git.stage(str(self.wt), ".gitignore")
        eng.git.commit_staged(str(self.wt), "ignore runner files")
        return eng

    def test_ignored_evidence_cannot_make_the_land_gate_green(self):
        relative = Path(".task/t-1/evidence/proof.txt")

        def check(cwd, env):
            return (0, "") if (Path(cwd) / relative).is_file() else (1, "missing evidence")

        eng = self.engine(procsim.fake("requires-evidence", check))
        proof = self.wt / relative
        proof.parent.mkdir(parents=True)
        proof.write_text("slot only")
        # A stage pass for the same tracked tree must not authorize delivery.
        self.assertFalse(eng.checker.run_items(gate_items(eng.cfg)).failed)
        self.assertFalse(Gate(eng).green())
        got = Gate(eng).run()
        self.assertIsInstance(got, Problem)
        assert isinstance(got, Problem)
        self.assertEqual(got.kind, ProblemKind.GATE)
        self.assertIn("missing evidence", got.text)
        self.assertEqual(proof.read_text(), "slot only")

    def test_checks_see_committed_files_and_declared_artifact_output(self):
        seen = []

        def check(cwd, env):
            root = Path(cwd)
            seen.append(root)
            self.assertEqual((root / "a.txt").read_text(), "a\n")
            self.assertFalse((root / "ignored.txt").exists())
            self.assertFalse((root / "untracked.txt").exists())
            self.assertEqual(env[EnvVar.TL_WORKTREE], str(root))
            (Path(env[EnvVar.TL_ARTIFACT_DIR]) / "result.txt").write_text("result")
            return 0, ""

        eng = self.engine(procsim.fake("clean-inputs", check))
        (self.wt / "ignored.txt").write_text("keep me")
        got = Gate(eng).run()
        self.assertIsInstance(got, GatePass)
        self.assertNotEqual(seen, [self.wt])
        self.assertTrue(all(not root.exists() for root in seen))
        self.assertEqual((self.wt / "ignored.txt").read_text(), "keep me")
        self.assertTrue(list(eng.run_dir.glob("artifacts/evidence/attempt-*/result.txt")))
        self.assertTrue(Gate(eng).green())
        Gate(eng).run()
        self.assertEqual(len(seen), 1)  # only a clean gate's pass can be reused

    def test_detached_checkout_is_removed_when_a_check_raises(self):
        seen = []

        def check(cwd, env):
            seen.append(Path(cwd))
            raise RuntimeError("check interrupted")

        eng = self.engine(procsim.fake("interrupted-gate", check))
        with self.assertRaisesRegex(RuntimeError, "check interrupted"):
            Gate(eng).run()
        self.assertTrue(seen)
        self.assertTrue(all(not root.exists() for root in seen))

    def test_checkout_failure_never_runs_checks_in_the_slot(self):
        eng = self.engine("true")
        with (mock.patch.object(eng.git, "add_worktree", side_effect=SlotGitError("checkout failed")),
              mock.patch.object(eng, "sh") as sh,
              self.assertRaisesRegex(SlotGitError, "checkout failed")):
            Gate(eng).run()
        sh.assert_not_called()

    def test_plan_producer_cannot_skip_a_check_using_ignored_slot_files(self):
        eng = self.engine("false")
        eng.cfg = eng.cfg.replace(plan_cmd=["repo-plan"])
        (self.wt / "ignored.txt").write_text("skip evidence")
        seen = []

        def plan(argv, **kw):
            root = Path(kw["cwd"])
            seen.append(root)
            self.assertFalse((root / "ignored.txt").exists())
            output = {"version": 1, "base": None, "empty": False, "full": True, "full_reasons": [], "steps": []}
            return Ran(exit=0, out=json.dumps(output))

        with (mock.patch("taskloop.app.checks.gateplan.shutil.which", return_value="repo-plan"),
              mock.patch.object(eng.spawner, "run", side_effect=plan)):
            got = Gate(eng).run()
        self.assertIsInstance(got, Problem)
        self.assertTrue(seen)
        self.assertTrue(all(not root.exists() for root in seen))

    def test_dirty_slot_is_refused_without_running_or_removing_its_work(self):
        eng = self.engine("true")
        (self.wt / "untracked.txt").write_text("keep me")
        self.assertFalse(Gate(eng).green())
        with mock.patch.object(eng, "sh") as sh, self.assertRaisesRegex(Blocked, "committed tree"):
            Gate(eng).run()
        sh.assert_not_called()
        self.assertEqual((self.wt / "untracked.txt").read_text(), "keep me")

    def test_check_cannot_mutate_the_clean_tree_and_cache_a_pass(self):
        def change(cwd, env):
            (Path(cwd) / "a.txt").write_text("changed by check")
            return 0, ""

        eng = self.engine(procsim.fake("mutates-tree", change))
        with self.assertRaisesRegex(Blocked, "changed its judged tree"):
            Gate(eng).run()
        self.assertEqual((self.wt / "a.txt").read_text(), "a\n")
        self.assertFalse(Gate(eng).green())
