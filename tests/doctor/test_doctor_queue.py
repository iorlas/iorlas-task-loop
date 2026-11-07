"""Queue diagnostics observe fake ports and never repair stored documents."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from taskloop.app.doctor.queue import findings, report
from taskloop.domain.land.queue_model import Entry, Phase
from taskloop.domain.land.queue_persist import to_doc
from tlkernel.queue_state import Incident, QueueState


def document(phase=Phase.WAITING):
    return to_doc([Entry(branch="task/a", head="head", phase=phase)], {}, in_flight=1, last_base="main")


def git_port(refs=(), paths=()):
    return SimpleNamespace(
        for_each_ref=lambda repo, prefix: [SimpleNamespace(name=ref) for ref in refs],
        checkouts=lambda repo: [SimpleNamespace(path=path) for path in paths],
        rev_parse=lambda repo, ref: "main", common_dir=lambda repo: "")


@pytest.mark.parametrize("doc,state", [(None, None), (None, QueueState()), (document(), None),
                                       (document(Phase.MERGED), None)])
def test_healthy_or_absent_queue(doc, state):
    assert findings(doc, state, git_port(), "repo", "origin/main", 10) == []


@pytest.mark.parametrize("doc", [None, document()])
def test_frozen_queue_names_newest_incident(doc):
    def incident(t, kind):
        return Incident(t=t, kind=kind, pr=12, bead="a", main_before="main", merge_sha="merge", parent="main",
                        expected_tree="a" * 40, landed_tree="b" * 40)
    state = QueueState(frozen=True, incidents=[incident(20, "corrupt"), incident(10, "raced")])
    lines = findings(doc, state, SimpleNamespace(), "repo", "origin/main", 10)
    assert len(lines) == 1
    assert "corrupt" in lines[0] and "PR #12" in lines[0] and "raced" not in lines[0]
    assert "a" * 12 in lines[0] and "b" * 12 in lines[0] and "a" * 13 not in lines[0]
    assert "nothing lands until the owner clears it" in lines[0]


@pytest.mark.parametrize("phase,refs,paths,expected", [
    (Phase.WAITING, ["refs/tl/queue/orphan"], [], "orphan ref refs/tl/queue/orphan"),
    (Phase.WAITING, [], ["repo/tl-land-gate-orphan"], "orphan worktree repo/tl-land-gate-orphan"),
    (Phase.GATING, [], [], "entry task/a must be reset: build lost or queue commit gone"),
    (Phase.GREEN, [], [], "entry task/a must be reset: build lost or queue commit gone"),
    (Phase.EJECTED, [], [], "ejected task/a not yet told"),
])
def test_recovery_is_described(phase, refs, paths, expected):
    assert findings(document(phase), None, git_port(refs, paths), "repo", "origin/main", 10) == [expected]


def test_report_prints_without_writing_stores():
    doc = document(Phase.GATING)
    queue_doc = Mock()
    queue_doc.get.return_value = doc
    state_doc = Mock()
    state_doc.get.return_value = None
    stores = Mock()
    stores.queue.of.return_value = queue_doc
    stores.queue_state.of.return_value = state_doc
    with patch("builtins.print") as printed:
        lines = report(stores, git_port(), "repo", "origin/main", 10)
    printed.assert_called_once_with(f"FAIL queue: {lines[0]}")
    assert queue_doc.get() == document(Phase.GATING)
    assert queue_doc.method_calls == [("get", (), {}), ("get", (), {})]
    assert state_doc.method_calls == [("get", (), {})]
    assert stores.queue.of.call_args == stores.queue_state.of.call_args
