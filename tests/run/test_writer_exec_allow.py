"""Engine requests carry product choices; delegate owns execution grants."""
from unittest import mock

import pytest

from taskloop.adapters import delegate as adapter
from taskloop.adapters import delegate_wire
from taskloop.app.workers import worker_identity, worker_request
from tlkernel.config import EngineConfig
from tlkernel.delegate import RunRequest


def test_contract_four_parses_and_three_is_a_violation():
    assert delegate_wire.result_of({"contract": 4, "stop": None}).stop is None
    stop = delegate_wire.result_of({"contract": 3, "stop": None}).stop
    assert stop is not None
    assert stop.reason == "contract_violation"


@pytest.mark.parametrize("role", ["worker", "planner", "reviewer", "reader"])
def test_request_scopes_product_flags(role):
    host = mock.Mock(session="s", bead="t-1")
    host.cfg = EngineConfig(writer_exec=True)
    host.budget.labels, host.plan_data = ["writer-family:codex-ish"], None
    host.git.diff_entries.return_value = []
    host.git.rev_parse.return_value = "base"
    host.checker.split.return_value.engine_recipes.return_value = []
    call = mock.Mock(node="write" if role == "worker" else role, role=role, cwd="/w", title="T", thread="writer")
    with mock.patch.object(worker_request.planref, "stage_commands", return_value=[]):
        req = worker_request.request(host, call, "live", 60, 30)
    assert req.prefer == ("codex-ish" if role == "worker" else "")
    assert req.writer_exec is (role == "worker")
    assert req.reviewer_other_family is (role == "reviewer")
    mapped = adapter.api_request(req, {})
    assert (mapped.prefer, mapped.writer_exec, mapped.reviewer_other_family) == (
        req.prefer, req.writer_exec, req.reviewer_other_family)
    assert not mapped.only_family and not mapped.writer_exec_allow and not mapped.read_roots and mapped.authored_by is None


@pytest.mark.parametrize("change", [{"writer_exec": True}, {"prefer": "codex-ish"}, {"reviewer_other_family": True}])
def test_product_choices_change_identity(change):
    req = RunRequest(role="worker", brief_path="b", cwd="/w", schema_path="s")
    ctx = worker_identity.ExecutionContext("/w", "/w", "tree", "tree", "head", "head")
    def fingerprint(request):
        return worker_identity.prepare_call(worker_identity.NodeInput("write", "prompt", {}, request), ctx, "contract-4").semantics
    assert fingerprint(req) != fingerprint(req.replace(**change))
