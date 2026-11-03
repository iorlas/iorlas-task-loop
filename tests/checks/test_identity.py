"""Authorization and reuse require the complete execution identity."""
import unittest
from argparse import Namespace
from unittest import mock

from support import procsim
from support.engine_case import EngineTest
from support.spawn import port_git

from taskloop.adapters import check_files
from taskloop.app.checks.attempts import Attempts, Outcome
from taskloop.app.checks.cache import InputKeys, RunMemo
from taskloop.app.checks.execution import EnvironmentUnavailable, ReadyExecution, image_identity, resolve_container
from taskloop.app.checks.gateplan import PlanDecision
from taskloop.app.checks.runner import cached_gate
from taskloop.app.land.cmds import Cmds
from taskloop.app.land.stackgate import StackGate
from taskloop.cli.green import cmd_green
from taskloop.contracts import wire
from taskloop.contracts.checks import Check, CheckResult, PassRecord
from taskloop.contracts.config import ContainerConfig, load
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import TreeEntry
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Git, Ran
from taskloop.contracts.runkey import BaseSha, Digest
from taskloop.domain.checks.specs import diff_check, gate_items
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class Identity(unittest.TestCase):
    def setUp(self):
        keys = InputKeys(port_git(), "/unused", TreeSha("tree"))
        keys.files = {}
        self.memo = RunMemo(fake_stores(), "repo", keys, BaseSha("base"), {})
        self.check = Check(id=CheckId("test"), cmd="true")

    def test_authorization_compares_every_key_field(self):
        key = self.memo.key(self.check)
        assert key is not None
        result = CheckResult(id=self.check.id, cmd="true", group="tests", exit=0, status="passed")
        self.memo.remember(key, result, 1, "")
        self.assertEqual(self.memo.result(self.check), result)
        changes = {"cmd": "false", "env": {"A": "changed"}, "selected": ["one"], "inputs_only": True}
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assertIsNone(self.memo.result(self.check.replace(**{field: value})))
        self.memo.system = "another-toolchain"
        self.assertIsNone(self.memo.result(self.check))

    def test_command_reuse_keeps_registry_and_execution_identity(self):
        self.assertNotEqual(self.memo.command_key(self.check), self.memo.command_key(self.check.replace(id=CheckId("other"))))
        self.assertNotEqual(self.memo.command_key(self.check), self.memo.command_key(self.check.replace(container=True)))

    def test_receipts_name_the_resolved_image(self):
        boxed = self.check.replace(container=True)
        self.memo.executions[boxed.id] = Digest("sha256:first")
        first = self.memo.key(boxed)
        self.memo.executions[boxed.id] = Digest("sha256:second")
        self.assertNotEqual(first, self.memo.key(boxed))
        self.memo.executions.clear()
        self.assertIsNone(self.memo.key(boxed))

    def test_dependency_readers_cannot_reuse_an_unresolved_receipt(self):
        self.assertIsNone(self.memo.key(self.check.replace(reads=[CheckId("producer")])))

    def test_changed_producer_evidence_invalidates_its_readers_receipt(self):
        producer = self.check.replace(id=CheckId("producer"))
        reader = self.check.replace(reads=[producer.id])
        self.memo.checks = {producer.id: producer, reader.id: reader}
        key = self.memo.key(producer)
        assert key is not None
        result = CheckResult(id=producer.id, cmd="true", group="tests", exit=0, status="passed", tail="first output")
        self.memo.remember(key, result, 1, "/first.log")
        first = self.memo.key(reader)
        self.assertIsNotNone(first)
        self.memo.remember(key, result.replace(tail="different output"), 2, "/second.log")
        self.assertNotEqual(first, self.memo.key(reader))

    def test_legacy_ambiguous_receipts_are_display_only(self):
        key = self.memo.key(self.check)
        assert key is not None
        result = CheckResult(id=self.check.id, cmd="true", group="tests", exit=0, status="passed")
        self.memo.remember(key.replace(execution=Digest("")), result, 1, "")
        self.assertIsNone(self.memo.result(self.check))

    def test_reader_key_survives_the_producers_receipt_wire_round_trip(self):
        producer = self.check.replace(id=CheckId("producer"), run_in="slot")
        reader = self.check.replace(reads=[producer.id])
        self.memo.checks = {producer.id: producer, reader.id: reader}
        key = self.memo.key(producer)
        assert key is not None
        result = CheckResult(id=producer.id, cmd="true", group="tests", exit=0, status="passed", secs=1)
        self.memo.remember(key, result, 1, "/producer.log")
        before = self.memo.key(reader)
        self.assertIsNotNone(before)
        receipt = self.memo.receipts[producer.id]
        self.memo.receipts[producer.id] = wire.load(PassRecord, wire.dump(receipt))
        self.assertEqual(self.memo.key(reader), before)

    def test_argv_identity_preserves_whitespace_inside_an_argument(self):
        self.assertNotEqual(self.memo.key(self.check.replace(cmd="echo 'a b'")),
                            self.memo.key(self.check.replace(cmd="echo 'a  b'")))


class Resolution(unittest.TestCase):
    def test_image_inspection_resolves_an_immutable_identity(self):
        spawner = mock.Mock()
        spawner.run.return_value = Ran(exit=0, out="sha256:resolved\n")
        self.assertEqual(image_identity(spawner, "mutable:tag"), "sha256:resolved")
        spawner.run.assert_called_once_with(
            ["docker", "image", "inspect", "--format", "{{.Id}}", "mutable:tag"], timeout_s=15)

    def test_missing_image_is_unavailable(self):
        spawner = mock.Mock()
        spawner.run.side_effect = [Ran(exit=0), Ran(exit=1)]
        result = resolve_container(ContainerConfig(image="missing"), "/unused", spawner)
        self.assertIsInstance(result, EnvironmentUnavailable)

    def test_dockerfile_context_is_rebuilt_before_identifying_the_image(self):
        spawner = mock.Mock()
        spawner.run.side_effect = [Ran(exit=0), Ran(exit=0, out="built"), Ran(exit=0, out="sha256:new-context")]
        result = resolve_container(ContainerConfig(dockerfile="build/Dockerfile"), "/repo", spawner)
        self.assertEqual(result, ReadyExecution(Digest("sha256:new-context"), "sha256:new-context"))
        self.assertEqual(spawner.run.call_args_list[1].args[0],
                         ["docker", "build", "-q", "-f", "/repo/build/Dockerfile", "/repo/build"])


class DeliveryIdentity(unittest.TestCase):
    def test_gate_stack_and_green_agree_on_changed_requirements(self):
        git = mock.create_autospec(Git, instance=True)
        git.config_get.return_value = "repo"
        git.ls_tree.return_value = []
        git.rev_parse.return_value = "base"
        git.merge_base.return_value = "base"
        tree, base, stores = TreeSha("tree"), BaseSha("base"), fake_stores()
        cfg = load({"engine": {"checks": [{"id": "test", "argv": ["true"], "run": "gate"}]}}).engine
        keys = InputKeys(git, "/repo", tree)
        memo = RunMemo(stores, check_files.repo_key(git, "/repo"), keys, base, {"TL_SLOT": "check"})
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
                    self.assertEqual(cmd_green(argv, ConfigDir("/unused"), git, lambda text: None) == 0, expected)
                self.assertEqual(not stack.red(engine, tree, base), expected)
                self.assertEqual(cached_gate(engine, git, "/repo", stores, Env(), {"TL_SLOT": "check"}, tree, PlanDecision({})),
                                 expected)
        git.ls_tree.return_value = [TreeEntry(mode="100644", kind="blob", oid="changed", path="mise.toml")]
        self.assertEqual(stack.red(cfg, tree, base), [CheckId("test")])


class UnavailableContainer(EngineTest):
    def test_distinct_ids_receive_their_own_injected_step_identity(self):
        seen = []
        cmd = procsim.fake("record-step", lambda cwd, env: (seen.append(env["TL_ARTIFACT_STEP"]) or 0, ""))
        eng = self.checks_engine(checks=[{"id": "first", "cmd": cmd}, {"id": "second", "cmd": cmd}])
        eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual(seen, ["first", "second"])

    def test_unavailable_container_never_launches_a_host_check_or_records_a_pass(self):
        eng = self.checks_engine(container={"image": "missing"}, checks=[
            {"id": "boxed", "cmd": "true", "in": "container", "run": "gate"}])
        with (mock.patch("taskloop.app.checks.execution.docker_ok", return_value=False), mock.patch.object(eng, "sh") as sh,
              mock.patch.object(eng.checker, "_diff_check", return_value=[])):
            run = eng.checker.run_items(gate_items(eng.cfg))
            self.assertEqual(run[0].status, "unverified")
            self.assertIn("environment unavailable", run[0].why)
            sh.assert_not_called()
            self.assertFalse(eng.checker.gate_green())

    def test_host_and_container_requirements_execute_separately(self):
        eng = self.checks_engine(container={"image": "mutable"}, checks=[
            {"id": "host", "cmd": "true", "run": "gate"},
            {"id": "boxed", "cmd": "true", "in": "container", "run": "gate"}])
        launched = []

        def run(check, *args):
            launched.append(check.id)
            return Outcome(int(check.container), "", "", 1, 0)

        ready = ReadyExecution(Digest("sha256:image"), "sha256:image")
        with (mock.patch("taskloop.app.checks.container.resolve_container", return_value=ready),
              mock.patch.object(Attempts, "run", side_effect=run), mock.patch.object(eng.checker, "_diff_check", return_value=[])):
            result = eng.checker.run_items(gate_items(eng.cfg))
        self.assertEqual(launched, ["host", "boxed"])
        self.assertEqual([r.status for r in result], ["passed", "failed"])
        memo = eng.checker._memo(result.tree, str(result.base))
        memo.executions[CheckId("boxed")] = ready.identity
        self.assertIsNone(memo.result(gate_items(eng.cfg)[1]))

    def test_restored_docker_and_changed_image_each_require_execution(self):
        eng = self.checks_engine(container={"image": "mutable"}, checks=[
            {"id": "boxed", "cmd": "true", "in": "container", "run": "gate"}])
        resolutions = [EnvironmentUnavailable("offline"), ReadyExecution(Digest("sha256:first"), "sha256:first"),
                       ReadyExecution(Digest("sha256:first"), "sha256:first"),
                       ReadyExecution(Digest("sha256:changed"), "sha256:changed")]
        with (mock.patch("taskloop.app.checks.container.resolve_container", side_effect=resolutions),
              mock.patch.object(Attempts, "run", return_value=Outcome(0, "", "", 1, 0)) as run,
              mock.patch.object(eng.checker, "_diff_check", return_value=[])):
            results = [eng.checker.run_items(gate_items(eng.cfg))[0] for _ in resolutions]
        self.assertEqual([r.status for r in results], ["unverified", "passed", "passed", "passed"])
        self.assertEqual([r.cached for r in results], [False, False, True, False])
        self.assertEqual(run.call_count, 2)
