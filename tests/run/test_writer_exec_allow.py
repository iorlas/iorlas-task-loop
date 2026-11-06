"""tl-auky: contract-4 writer grants are explicit, admitted, scoped and part of recovery identity."""
import json
from unittest import mock

import pytest
import support.paths  # noqa: F401
from support import engine_case as te
from support import fake_route
from support.argv_of import argv_of
from support.case import Case

from taskloop.adapters import delegate_wire
from taskloop.app.run import worker_identity, worker_request
from taskloop.contracts import config
from taskloop.contracts.delegate import RunRequest
from taskloop.domain.lanes import pin

GRANT = [["just", "unity-shot"], ["tool", "an argument"]]


class WriterGrant(Case):
    def test_contract_four_parses_and_three_is_a_violation(self):
        assert delegate_wire.result_of({"contract": 4, "stop": None}).stop is None
        stop = delegate_wire.result_of({"contract": 3, "stop": None}).stop
        assert stop is not None
        assert stop.reason == "contract_violation"

    def test_profile_shape_and_default(self):
        assert config.load({}).engine.writer_exec_allow == []
        assert config.load({"engine": {"writer_exec_allow": GRANT}}).engine.writer_exec_allow == GRANT
        for value in (None, "just shot", {}, ["just"], [[]], [[""]], [["just", ""]], [["just", 1]]):
            with self.subTest(value=value), pytest.raises(config.ConfigError, match="writer_exec_allow"):
                config.load({"engine": {"writer_exec_allow": value}})

    def test_only_writer_calls_carry_compact_json_and_empty_sends_no_flag(self):
        for node, role in (("write", "worker"), ("plan", "planner"), ("review", "reviewer"),
                           ("reflect", "reviewer"), ("read", "reader")):
            for grant in ([], GRANT):
                with self.subTest(node=node, grant=grant):
                    host = mock.Mock(session="s", bead="t-1")
                    host.cfg = config.EngineConfig(writer_family=["openai"], writer_exec_allow=grant)
                    host.budget.labels = []
                    host.git.diff_entries.return_value = []
                    host.checker.split.return_value.engine_recipes.return_value = []
                    call = mock.Mock(node=node, role=role, cwd="/w", title="T", resume=None, writer=None)
                    with mock.patch.object(worker_request.planref, "stage_commands", return_value=[]):
                        req = worker_request.request(host, call, "live", 60, 30)
                    argv = argv_of(req)
                    if role == "worker" and grant:
                        assert json.loads(argv[argv.index("--writer-exec-allow") + 1]) == [["just", "unity-shot"], ["tool", "an argument"]]
                    else:
                        assert "--writer-exec-allow" not in argv

    def test_a_changed_grant_changes_the_request_fingerprint(self):
        req = RunRequest(role="worker", brief_path="b", cwd="/w", schema_path="s")
        ctx = worker_identity.ExecutionContext("/w", "/w", "tree", "tree", "head", "head")

        def fingerprint(grant):
            data = worker_identity.NodeInput("write", "prompt", {}, req.replace(writer_exec_allow=grant))
            return worker_identity.prepare_call(data, ctx, "contract-4").semantics

        assert fingerprint([]) != fingerprint(GRANT)
        assert fingerprint(GRANT) != fingerprint([["just", "other"]])

    def test_grant_capability_is_an_advertised_list_under_contract_four(self):
        for contract, capabilities in ((3, ["writer_exec_allow"]), (4, None), (4, "writer_exec_allow"), (4, [])):
            with self.subTest(contract=contract, capabilities=capabilities):
                assert "capability" in pin.exec_allow_problem(GRANT, ["openai"], [], contract, capabilities)


class Admission(te.EngineTest):
    def test_missing_capability_refuses_before_any_worker_but_empty_is_fine(self):
        handshake = {**fake_route.CONTRACT, "capabilities": []}
        with mock.patch.dict(fake_route.CONTRACT, handshake, clear=True):
            rc, script = self.run_engine({"plan": [te.PLAN]}, writer_family=["openai"], writer_exec_allow=GRANT)
        assert rc == 2
        assert script.nodes == []
        assert "writer_exec_allow" in self.said()
        assert "capability" in self.said()

    def test_empty_grant_does_not_require_capability(self):
        with mock.patch.dict(fake_route.CONTRACT, {**fake_route.CONTRACT, "capabilities": []}, clear=True):
            rc, script = self.run_engine({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        assert rc == 0
        assert "write" in script.nodes
        assert all("--writer-exec-allow" not in argv for argv in script.argvs)

    def test_nonempty_grant_requires_exact_openai_profile_and_effective_pin(self):
        for family, labels in (([], []), (["claude"], []), (["openai", "xai"], []),
                               (["openai"], ["writer-family:xai"])):
            with self.subTest(family=family, labels=labels), self.store.stub(show=dict(te.BEAD, labels=labels)):
                rc, script = self.run_engine({"plan": [te.PLAN]}, writer_family=family,
                                             writer_exec_allow=GRANT)
                assert rc == 2
                assert script.nodes == []
                assert "openai" in self.said()

    def test_admitted_grant_reaches_only_the_writer(self):
        rc, script = self.run_engine({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]},
                                     writer_family=["openai"], writer_exec_allow=[*GRANT, [te.HAS_F]])  # the plan's own check runs too
        assert rc == 0
        assert "write" in script.nodes
        for node, argv in zip(script.nodes, script.argvs, strict=True):
            assert ("--writer-exec-allow" in argv) == (node == "write")


for _name in dir(te.EngineTest):
    if _name.startswith("test_") and _name not in Admission.__dict__:
        setattr(Admission, _name, None)
