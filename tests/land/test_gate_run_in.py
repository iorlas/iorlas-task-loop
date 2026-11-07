"""A mixed gate preserves its plan while setup-dependent checks run in the committed slot."""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.engine_case import EngineTest
from support.gate_rig import GateCase
from support.plans import CLEAN, PLAN, WRITE

from taskloop.app.land.gate import Gate, GatePass, Problem
from tlgate.clean import isolated
from tlgate.domain.specs import gate_items
from tlgate.host import CheckFault
from tlgate.runner import cached_gate
from tlkernel.checks import CheckFaultKind
from tltestkit import procsim


class SlotGate(GateCase):
    def engine(self, checks, **cfg):
        eng = self.checks_engine(checks=checks, **cfg)
        (self.wt / ".gitignore").write_text(".task/\nsetup.txt\n")
        eng.git.stage(str(self.wt), ".gitignore")
        if eng.checkout.tree_hash() != eng.git.rev_parse(str(self.wt), "HEAD^{tree}"):
            eng.git.commit_staged(str(self.wt), "ignore setup")
        (self.wt / "setup.txt").write_text("installed")
        return eng

    def test_slot_check_uses_setup_and_resource_lease_and_cached_gate_matches(self):
        seen = []

        def check(cwd, env):
            seen.append(Path(cwd))
            assert Path(cwd) == self.wt
            assert (Path(cwd) / "setup.txt").read_text() == "installed"
            assert eng.stores.leases.holders("unity", 1)
            held = (env.get("ANY_LEASE_HELD"), env.get("ANY_LEASE_ROOT"))  # what a run wrapper inside the command reads
            assert held == ("unity", str(eng.stores.leases.root))
            return 0, ""

        eng = self.engine([{"id": "unity", "cmd": procsim.fake("slot-setup", check), "run": "gate",
                            "run_in": "slot", "needs": ["unity"]}], resources={"unity": {"limit": 1}})
        assert not Gate(eng).green()
        assert isinstance(Gate(eng).run(), GatePass)
        assert Gate(eng).green()
        assert isinstance(Gate(eng).run(), GatePass)
        assert seen == [self.wt]
        assert not eng.stores.leases.holders("unity", 1)

    def test_mixed_checks_keep_plan_order_and_each_cwd(self):
        seen = []

        def command(name, rc=0):
            def check(cwd, env):
                seen.append((name, Path(cwd)))
                return rc, ""
            return procsim.fake("mixed-" + name, check)

        eng = self.engine([
            {"id": "first", "cmd": command("first"), "run": "gate", "run_in": "slot", "group": "static"},
            {"id": "second", "cmd": command("second"), "run": "gate", "group": "tests"},
            {"id": "third", "cmd": command("third"), "run": "gate", "run_in": "slot", "group": "acceptance"},
        ])
        run = eng.checker.run_items(gate_items(eng.cfg), clean=True)
        assert not run.failed
        assert [name for name, _ in seen] == ["first", "second", "third"]
        assert [root == self.wt for _, root in seen] == [True, False, True]
        assert eng.checker.gate_green(clean=True)
        eng.checker.run_items(gate_items(eng.cfg), clean=True)
        assert len(seen) == 3

    def test_red_in_either_location_skips_the_later_group(self):
        for location in ("clean", "slot"):
            with self.subTest(location=location):
                eng = self.engine([
                    {"id": "red", "cmd": "false", "run": "gate", "run_in": location, "group": "static"},
                    {"id": "later", "cmd": "true", "run": "gate",
                     "run_in": "slot" if location == "clean" else "clean"},
                ])
                run = eng.checker.run_items(gate_items(eng.cfg), clean=True)
                assert [(r.id, r.status) for r in run] == [("red", "failed"), ("later", "skipped")]
                assert not eng.checker.gate_green(clean=True)
                assert isinstance(Gate(eng).run(), Problem)
                assert Gate(eng).passed() is None

    def test_slot_input_changes_invalidate_gate_and_preview_memos(self):
        eng = self.engine([{"id": "slot", "cmd": "true", "run": "gate", "run_in": "slot",
                            "inputs": ["**"], "inputs_only": True}])
        eng.checker.run_items(gate_items(eng.cfg), clean=True)

        def preview_green():
            return cached_gate(eng.cfg, eng.git, str(self.wt), eng.stores, eng.env,
                               eng.checkout.tree_hash(), None, clean=True, slot_wt=str(self.wt))

        assert eng.checker.gate_green(clean=True)
        assert Gate(eng).green()
        assert preview_green()
        (self.wt / "setup.txt").write_text("new installation")
        assert not eng.checker.gate_green(clean=True)
        assert not Gate(eng).green()
        assert not preview_green()

    def test_fresh_reader_cannot_reuse_a_slot_receipt_without_its_ignored_inputs(self):
        eng = self.engine([
            {"id": "producer", "cmd": "true", "run": "gate", "run_in": "slot", "inputs": ["**"]},
            {"id": "reader", "cmd": "true", "run": "gate", "reads": ["producer"]},
        ])
        assert isinstance(Gate(eng).run(), GatePass)
        assert Gate(eng).green()
        with isolated(eng) as fresh:
            assert not (Path(fresh.wt) / "setup.txt").exists()
            assert not cached_gate(eng.cfg, eng.git, str(fresh.wt), eng.stores, eng.env,
                                         eng.checkout.tree_hash(), None, clean=True)

    def test_clean_reader_consumes_the_slot_producers_receipt_and_log(self):
        def producer(cwd, env):
            assert Path(cwd) == self.wt
            return 0, "slot proof"

        def reader(cwd, env):
            assert Path(cwd) != self.wt
            assert "slot proof" in Path(env["TL_CHECK_LOG_PRODUCER"]).read_text()
            assert env["TL_CHECK_RC_PRODUCER"] == "0"
            return 0, ""

        eng = self.engine([
            {"id": "producer", "cmd": procsim.fake("slot-producer", producer), "run": "gate", "run_in": "slot"},
            {"id": "reader", "cmd": procsim.fake("clean-reader", reader), "run": "gate", "reads": ["producer"]},
        ])
        run = eng.checker.run_items(gate_items(eng.cfg), clean=True)
        assert [(r.id, r.status) for r in run] == [("producer", "passed"), ("reader", "passed")]
        assert eng.checker.gate_green(clean=True)

    def test_dirty_slot_is_refused_before_any_check(self):
        eng = self.engine([{"id": "slot", "cmd": "true", "run": "gate", "run_in": "slot"}])
        (self.wt / "untracked.txt").write_text("keep")
        with mock.patch.object(eng, "sh") as sh, pytest.raises(CheckFault) as fault:
            eng.checker.run_items(gate_items(eng.cfg), clean=True)
        assert fault.value.kind == CheckFaultKind.DIRTY_SLOT
        sh.assert_not_called()
        assert not eng.checker.gate_green(clean=True)

    def test_slot_check_cannot_change_the_judged_tree(self):
        def change(cwd, env):
            (Path(cwd) / "a.txt").write_text("changed")
            return 0, ""

        eng = self.engine([{"id": "slot", "cmd": procsim.fake("slot-mutator", change), "run": "gate", "run_in": "slot"}])
        with pytest.raises(CheckFault, match="changed its judged tree"):
            eng.checker.run_items(gate_items(eng.cfg), clean=True)
        assert not eng.checker.gate_green(clean=True)


class SlotGateFlow(EngineTest):
    """One whole run: the setup stays in the slot and the clean gate's checkout lands."""

    def test_client_change_lands_with_setup_only_in_the_slot(self):
        seen = []
        # Reset starts the task from origin/main, so the ignore rule must live on
        # the base; a prep-only commit would disappear and expose setup as a stray.
        self.put_repo_file(".gitignore", ".task/\nclient/Library/\n")

        def prepare(_eng):
            installed = self.wt / "client/Library"
            installed.mkdir(parents=True, exist_ok=True)
            (installed / "setup").write_text("installed")

        def write(script, node, cwd, resume):
            (Path(cwd) / "client/main.cs").write_text("class Client {}\n")
            return WRITE

        def slot_check(cwd, env):
            seen.append("slot")
            assert Path(cwd) == self.wt
            assert (Path(cwd) / "client/Library/setup").read_text() == "installed"
            assert (Path(cwd) / "client/main.cs").is_file()
            return 0, ""

        def clean_check(cwd, env):
            seen.append("clean")
            assert Path(cwd) != self.wt
            assert not (Path(cwd) / "client/Library/setup").exists()
            assert (Path(cwd) / "client/main.cs").is_file()
            return 0, ""

        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], files=["f.txt", "client/main.cs"])])
        rc, script = self.run_engine({"plan": [plan], "write": [write], "review": [CLEAN]}, prep=prepare, checks=[
            {"id": "client-slot", "cmd": procsim.fake("client-slot", slot_check), "run": "gate",
             "run_in": "slot", "inputs": ["client/**"]},
            {"id": "client-clean", "cmd": procsim.fake("client-clean", clean_check), "run": "gate"},
        ])
        assert rc == 0, self.blocked
        assert self.eng.result().outcome == "landed"
        assert script.nodes == ["plan", "write", "review"]
        assert self.eng.git.show(str(self.wt), self.eng.landed_sha, "client/main.cs") == "class Client {}\n"
        landed_paths = [entry.path for entry in self.eng.git.ls_tree(str(self.wt), self.eng.landed_sha, recursive=True)]
        assert "client/Library/setup" not in landed_paths
        assert "slot" in seen
        assert "clean" in seen
