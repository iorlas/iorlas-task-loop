"""The land gate judges committed files, independently of the slot's ignored state."""
import json
import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.gate_rig import GateCase

from taskloop.app.land.gate import Gate, GatePass, Problem, ProblemKind
from tlgate.domain.specs import gate_items
from tlkernel.envvars import EnvVar
from tlkernel.procport import Ran
from tlkernel.slots import SlotGitError
from tlpipeline.blocked import Blocked
from tltestkit import procsim


class CleanGate(GateCase):
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
        proof.parent.mkdir(parents=True, exist_ok=True)
        proof.write_text("slot only")
        # A stage pass for the same tracked tree must not authorize delivery.
        assert not eng.checker.run_items(gate_items(eng.cfg)).failed
        assert not Gate(eng).green()
        got = Gate(eng).run()
        assert isinstance(got, Problem)
        assert isinstance(got, Problem)
        assert got.kind == ProblemKind.GATE
        assert "missing evidence" in got.text
        assert proof.read_text() == "slot only"

    def test_checks_see_committed_files_and_declared_artifact_output(self):
        seen = []

        def check(cwd, env):
            root = Path(cwd)
            seen.append(root)
            assert (root / "a.txt").read_text() == "a\n"
            assert not (root / "ignored.txt").exists()
            assert not (root / "untracked.txt").exists()
            assert env[EnvVar.TL_WORKTREE] == str(root)
            (Path(env[EnvVar.TL_ARTIFACT_DIR]) / "result.txt").write_text("result")
            return 0, ""

        eng = self.engine(procsim.fake("clean-inputs", check))
        (self.wt / "ignored.txt").write_text("keep me")
        got = Gate(eng).run()
        assert isinstance(got, GatePass)
        assert seen != [self.wt]
        assert all(not root.exists() for root in seen)
        assert (self.wt / "ignored.txt").read_text() == "keep me"
        assert list(eng.run_dir.glob("attempts/*/artifacts/evidence/attempt-*/result.txt"))
        assert Gate(eng).green()
        Gate(eng).run()
        assert len(seen) == 1  # only a clean gate's pass can be reused

    def test_detached_checkout_is_removed_when_a_check_raises(self):
        seen = []

        def check(cwd, env):
            seen.append(Path(cwd))
            raise RuntimeError("check interrupted")

        eng = self.engine(procsim.fake("interrupted-gate", check))
        with pytest.raises(RuntimeError, match="check interrupted"):
            Gate(eng).run()
        assert seen
        assert all(not root.exists() for root in seen)

    def test_checkout_failure_never_runs_checks_in_the_slot(self):
        eng = self.engine("true")
        with (mock.patch.object(eng.git, "add_worktree", side_effect=SlotGitError("checkout failed")),
              mock.patch.object(eng, "sh") as sh,
              pytest.raises(SlotGitError, match="checkout failed")):
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
            assert not (root / "ignored.txt").exists()
            output = {"version": 1, "base": None, "empty": False, "full": True, "full_reasons": [], "steps": []}
            return Ran(exit=0, out=json.dumps(output))

        real_which = shutil.which

        def which(name, **kw):  # only the plan word is faked: `nice` and the rest resolve as on the host
            return "repo-plan" if name == "repo-plan" else real_which(name, **kw)

        with (mock.patch("tlgate.gateplan.shutil.which", side_effect=which),
              mock.patch.object(eng.spawner, "run", side_effect=plan)):
            got = Gate(eng).run()
        assert isinstance(got, Problem)
        assert seen
        assert all(not root.exists() for root in seen)

    def test_dirty_slot_is_refused_without_running_or_removing_its_work(self):
        eng = self.engine("true")
        (self.wt / "untracked.txt").write_text("keep me")
        assert not Gate(eng).green()
        with mock.patch.object(eng, "sh") as sh, pytest.raises(Blocked, match="committed tree"):
            Gate(eng).run()
        sh.assert_not_called()
        assert (self.wt / "untracked.txt").read_text() == "keep me"

    def test_check_cannot_mutate_the_clean_tree_and_cache_a_pass(self):
        def change(cwd, env):
            (Path(cwd) / "a.txt").write_text("changed by check")
            return 0, ""

        eng = self.engine(procsim.fake("mutates-tree", change))
        with pytest.raises(Blocked, match="changed its judged tree"):
            Gate(eng).run()
        assert (self.wt / "a.txt").read_text() == "a\n"
        assert not Gate(eng).green()
