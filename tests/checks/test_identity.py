"""Authorization and reuse require the complete execution identity."""
from argparse import Namespace
from pathlib import Path
from unittest import mock

from support.check_host import CheckHostCase
from support.memstores import fake_stores
from support.spawn import port_git

from taskloop.app.land.cmds import Cmds
from taskloop.app.land.stackgate import StackGate
from taskloop.cli.green import cmd_green
from taskloop.stores.real import real_stores
from taskloop.stores.runlog import RunLog
from tlgate.cache import KEEP, InputKeys, RunnerMemo
from tlgate.domain.specs import diff_check, gate_items
from tlgate.gateplan import PlanDecision
from tlgate.runner import cached_gate
from tlkernel import check_files, factorydb, wire
from tlkernel.checks import Check, CheckResult, PassRecord
from tlkernel.config import load
from tlkernel.env import Env
from tlkernel.gitfacts import TreeEntry
from tlkernel.gitport import Git
from tlkernel.ids import CheckId, TreeSha
from tlkernel.paths import ConfigDir
from tlkernel.runkey import BaseSha, Digest
from tltestkit import procsim
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


class Identity(Case):
    def setup_method(self):
        keys = InputKeys(port_git(), "/unused", TreeSha("tree"))
        keys.files = {}
        self.memo = RunnerMemo(fake_stores(), "repo", keys, BaseSha("base"), {})
        self.check = Check(id=CheckId("test"), cmd="true")

    def test_authorization_compares_every_key_field(self):
        key = self.memo.key(self.check)
        assert key is not None
        result = CheckResult(id=self.check.id, cmd="true", group="tests", exit=0, status="passed")
        self.memo.remember(key, result, 1, "")
        assert self.memo.result(self.check) == result
        changes = {"cmd": "false", "env": {"A": "changed"}, "selected": ["one"], "inputs_only": True}
        for field, value in changes.items():
            with self.subTest(field=field):
                assert self.memo.result(self.check.replace(**{field: value})) is None
        self.memo.system = "another-toolchain"
        assert self.memo.result(self.check) is None

    def test_command_reuse_keeps_registry_and_execution_identity(self):
        assert self.memo.command_key(self.check) != self.memo.command_key(self.check.replace(id=CheckId("other")))

    def test_dependency_readers_cannot_reuse_an_unresolved_receipt(self):
        assert self.memo.key(self.check.replace(reads=[CheckId("producer")])) is None

    def test_changed_producer_evidence_invalidates_its_readers_receipt(self):
        producer = self.check.replace(id=CheckId("producer"))
        reader = self.check.replace(reads=[producer.id])
        self.memo.checks = {producer.id: producer, reader.id: reader}
        key = self.memo.key(producer)
        assert key is not None
        result = CheckResult(id=producer.id, cmd="true", group="tests", exit=0, status="passed", tail="first output")
        self.memo.remember(key, result, 1, "/first.log")
        first = self.memo.key(reader)
        assert first is not None
        self.memo.remember(key, result.replace(tail="different output"), 2, "/second.log")
        assert first != self.memo.key(reader)

    def test_legacy_ambiguous_receipts_are_display_only(self):
        key = self.memo.key(self.check)
        assert key is not None
        result = CheckResult(id=self.check.id, cmd="true", group="tests", exit=0, status="passed")
        self.memo.remember(key.replace(execution=Digest("")), result, 1, "")
        assert self.memo.result(self.check) is None

    def test_reader_key_survives_the_producers_receipt_wire_round_trip(self):
        producer = self.check.replace(id=CheckId("producer"), run_in="slot")
        reader = self.check.replace(reads=[producer.id])
        self.memo.checks = {producer.id: producer, reader.id: reader}
        key = self.memo.key(producer)
        assert key is not None
        result = CheckResult(id=producer.id, cmd="true", group="tests", exit=0, status="passed", secs=1)
        self.memo.remember(key, result, 1, "/producer.log")
        before = self.memo.key(reader)
        assert before is not None
        receipt = self.memo.receipts[producer.id]
        self.memo.receipts[producer.id] = wire.load(PassRecord, wire.dump(receipt))
        assert self.memo.key(reader) == before

    def test_argv_identity_preserves_whitespace_inside_an_argument(self):
        assert self.memo.key(self.check.replace(cmd="echo 'a b'")) != self.memo.key(self.check.replace(cmd="echo 'a  b'"))


class DatabaseIdentity(Identity):
    """The CHECKIDENT corpus must give the same answers through the production DB store."""

    def setup_method(self):
        super().setup_method()
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(factorydb.close_shared)
        self.cfg = ConfigDir(Path(tmp.name))
        self.memo = RunnerMemo(real_stores(self.cfg), self.memo.repo, self.memo.keys, self.memo.base,
                               self.memo.engine_env, self.memo.run_id, executor=self.memo.executor)

    def test_remember_hit_latest_and_base_red_survive_a_new_store_bundle(self):
        key = self.memo.key(self.check)
        assert key is not None
        result = CheckResult(id=self.check.id, cmd=self.check.cmd, group="tests", exit=0, status="passed")
        self.memo.remember(key, result, 4, "/logs/check")
        self.memo.set_base_red(self.check, True)
        self.memo = RunnerMemo(real_stores(self.cfg), self.memo.repo, self.memo.keys, self.memo.base,
                               self.memo.engine_env, self.memo.run_id, executor=self.memo.executor)
        self.memo.receipts.clear()
        hit = self.memo.hit(key)
        assert hit is not None
        assert hit.result == result
        assert self.memo.latest(self.check) == hit
        assert self.memo.result(self.check) == result
        assert self.memo.base_was_red(self.check)
        assert not (self.cfg.root / "results").exists()
        assert self.memo.hit(key.replace(execution=Digest("different"))) is None

    def test_remember_prunes_to_the_newest_eight_receipts(self):
        keys = []
        for i in range(KEEP + 3):
            self.memo.keys.tree = TreeSha(f"tree-{i}")
            key = self.memo.key(self.check)
            assert key is not None
            keys.append(key)
            result = CheckResult(id=self.check.id, cmd=self.check.cmd, group="tests", exit=0, status="passed")
            with mock.patch("tlgate.cache.time.time", return_value=float(i)):
                self.memo.remember(key, result, i, "")
        assert len(self.memo.stores.results("repo", self.check.id).keys()) == KEEP
        assert self.memo.hit(keys[0]) is None
        assert self.memo.hit(keys[-1]) is not None
        assert self.memo.latest(self.check) == self.memo.hit(keys[-1])


class DeliveryIdentity(Case):
    def stores(self):
        return fake_stores()

    def test_gate_stack_and_green_agree_on_changed_requirements(self):
        git = mock.create_autospec(Git, instance=True)
        git.config_get.return_value = "repo"
        git.ls_tree.return_value = []
        git.rev_parse.return_value = "base"
        git.merge_base.return_value = "base"
        tree, base, stores = TreeSha("tree"), BaseSha("base"), self.stores()
        cfg = load({"engine": {"checks": [{"id": "test", "argv": ["true"], "run": "gate"}]}}).engine
        keys = InputKeys(git, "/repo", tree)
        memo = RunnerMemo(stores, check_files.repo_key(git, "/repo"), keys, base, {"TL_SLOT": "check"})
        for check in [*gate_items(cfg), diff_check(base, tree)]:
            key = memo.key(check)
            assert key is not None
            result = CheckResult(id=check.id, cmd=check.cmd, group=check.group, exit=0, status="passed")
            memo.remember(key, result, 1, "")
        log = RunLog(stores.run_log("gate"), run_id="gate", host="host")
        stack = StackGate(Cmds(mock.Mock(), log, "/repo"), git, stores, "/repo", "main", ["tl"])
        variants = [({}, True), ({"argv": ["false"]}, False), ({"env": {"MODE": "different"}}, False)]
        for changes, expected in variants:
            with self.subTest(changes=changes), mock.patch("taskloop.cli.green.real_stores", return_value=stores):
                profile = {"engine": {"checks": [{"id": "test", "argv": ["true"], "run": "gate", **changes}]}}
                engine = load(profile).engine
                with mock.patch("taskloop.cli.green.authorization.profile", return_value=engine):
                    argv = Namespace(repo="/repo", step="test", tree=tree, base=base)
                    assert (cmd_green(argv, ConfigDir("/unused"), git, lambda text: None) == 0) == expected
                assert (not stack.red(engine, tree, base)) == expected
                assert cached_gate(engine, git, "/repo", stores, Env(), tree, PlanDecision({})) == expected
        git.ls_tree.return_value = [TreeEntry(mode="100644", kind="blob", oid="changed", path="mise.toml")]
        assert stack.red(cfg, tree, base) == [CheckId("test")]


class DatabaseDeliveryIdentity(DeliveryIdentity):
    """Authorization, stack gate and green queries keep their full-key checks over SQL receipts."""

    def stores(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(factorydb.close_shared)
        return real_stores(ConfigDir(Path(tmp.name)))


class StepIdentity(CheckHostCase):
    def test_distinct_ids_receive_their_own_injected_step_identity(self):
        seen = []
        cmd = procsim.fake("record-step", lambda cwd, env: (seen.append(env["TL_ARTIFACT_STEP"]) or 0, ""))
        eng = self.checks_engine(checks=[{"id": "first", "cmd": cmd}, {"id": "second", "cmd": cmd}])
        eng.run_checks({"checks": [], "files": []}, "s")
        assert seen == ["first", "second"]
