"""tl-7i9k.58: a reviewer's request carries the base commit, so delegate gives it the base's instruction files; no other role does."""
from unittest import mock

import pytest
from support.argv_of import argv_of

from taskloop.app.run import worker_identity, worker_request
from taskloop.contracts import config
from taskloop.contracts.delegate import RunRequest


def build(role: str, node: str, resolved: str = "basesha"):
    host = mock.Mock(session="s", bead="t-1")
    host.cfg = config.EngineConfig()
    host.budget.labels, host.plan_data = [], None
    host.git.rev_parse.return_value = resolved
    host.git.diff_entries.return_value = []
    host.checker.split.return_value.engine_recipes.return_value = []
    call = mock.Mock(node=node, role=role, cwd="/w", title="T", resume=None, writer=None)
    with mock.patch.object(worker_request.planref, "stage_commands", return_value=[]), \
            mock.patch.object(worker_request.trustroots, "refusal", return_value=""):
        return worker_request.request(host, call, "live", 60, 30), host


@pytest.mark.parametrize(("role", "node", "expected"), [("reviewer", "review", "basesha"), ("reviewer", "verify", "basesha"),
                                                         ("worker", "write", ""), ("planner", "plan", "")])
def test_only_a_reviewer_is_given_the_base_commit(role, node, expected):
    req, host = build(role, node)
    assert req.instructions_ref == expected
    assert ("--instructions-ref" in argv_of(req)) == bool(expected)
    if expected:
        host.git.rev_parse.assert_called_once_with(host.wt, host.cfg.base)


def test_a_base_that_does_not_resolve_is_said_not_silent():
    req, host = build("reviewer", "review", resolved="")
    assert req.instructions_ref == ""
    assert "does not resolve" in host.log.warn.call_args.args[0]


def test_the_ref_is_part_of_the_call_identity_and_an_empty_one_changes_nothing():
    base = RunRequest(role="reviewer", brief_path="b", cwd="/w", schema_path="s")
    ctx = worker_identity.ExecutionContext("/w", "/w", "tree", "tree", "head", "head")

    def fingerprint(req):
        return worker_identity.prepare_call(worker_identity.NodeInput("review", "prompt", {}, req), ctx, "contract-4").semantics

    assert fingerprint(base) != fingerprint(base.replace(instructions_ref="abc"))
    assert fingerprint(base) == fingerprint(base.replace(instructions_ref=""))
