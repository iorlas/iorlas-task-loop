"""Whole prompts retain handoff text so delegate can choose a fresh worker."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from taskloop.app.workers.worker_identity import ExecutionContext, NodeInput, prepare_call
from taskloop.app.write import write_round
from taskloop.app.write.state import RoundResult, StageState
from taskloop.app.write.write_round import WriteRound
from tlkernel.config import EngineConfig
from tlkernel.delegate import RunRequest
from tltestkit.tmpdir import TemporaryDirectory


@pytest.mark.parametrize("delta,boundary,expected", [(None, False, ""), (None, True, ""),
    ("delta", False, "so far"), ("delta", True, "accepted")])
def test_whole_prompt_carries_handoff_only_with_delta(monkeypatch, delta, boundary, expected):
    monkeypatch.setattr(write_round, "write_prompt", lambda *a, **kw: "whole")
    monkeypatch.setattr(write_round, "anchors_text", lambda st: "")
    with TemporaryDirectory() as folder:
        host = NS(cfg=EngineConfig(), writer=NS(last_stage=True), review=NS(unchecked=[]),
            briefing=NS(stage_checks_text=lambda *a, **kw: "", where=lambda *a, **kw: ""),
            judge=NS(look_write=lambda st: ""), briefs=NS(text=lambda: "brief"),
            cases=NS(rules_text=lambda: "", plan_text=lambda i: ""), evidence_dir=folder,
            hand=NS(delta=lambda *a: delta, so_far_text=lambda: "so far", accepted_text=lambda: "accepted"),
            brief_file=Path(folder) / "brief", shared=NS(shared_text=lambda: ""),
            routing=NS(ledger=lambda: NS(text=lambda: "")))
        stage = StageState({"stages": [
            {"checks": [], "files": []},
            {"checks": [], "goal": "goal", "files": []},
            {"checks": [], "files": []},
        ]}, 1, None)
        stage.failed_cmds = []
        whole, sent = WriteRound(host).prompts(stage, boundary)
        assert sent == delta
        assert ("so far" in whole) == (expected == "so far")
        assert ("accepted" in whole) == (expected == "accepted")


def test_first_write_of_later_stage_sends_delta_and_boundary(monkeypatch):
    calls = []
    host = NS(ai=lambda *a, **kw: (calls.append(kw) or NS(data={}, family="claude")),
              pictures=NS(stage_visual=lambda st: False))
    runner = WriteRound(host)
    monkeypatch.setattr(runner, "prompts", lambda s, boundary: ("whole", "delta"))
    monkeypatch.setattr(runner, "record", lambda *a: None)
    monkeypatch.setattr(write_round.Prepare, "retry", lambda *a: True)
    stage = StageState({"stages": [{"checks": [], "files": []}, {"checks": [], "files": []}]}, 1, None)
    stage.n = 1
    runner.go(stage, RoundResult(), False)
    assert calls[0]["delta"] == "delta"
    assert calls[0]["boundary"] is True


def test_boundary_changes_call_identity():
    request = RunRequest(role="worker", brief_path="", cwd="tree", schema_path="", thread="writer")
    context = ExecutionContext("tree", "tree", "tree-sha", "tree-sha", "head", "head")
    ordinary = prepare_call(NodeInput("write", "whole", {}, request), context, "version")
    boundary = prepare_call(NodeInput("write", "whole", {}, request.replace(boundary=True)), context, "version")
    assert ordinary.semantics != boundary.semantics
