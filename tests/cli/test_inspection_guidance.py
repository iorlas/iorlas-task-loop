"""Inspection refusals retain structured fields and gain context-specific human remedies."""

import ast
import json
from pathlib import Path
from typing import Literal, get_args

import pytest
from refusal_inventory import ROOT

from taskloop import cli, cli_composition
from taskloop.drain.models import Conclusion, Result
from taskloop.drain.render import GUIDE as DRAIN_GUIDE
from taskloop.drain.render import human as drain_human
from taskloop.inspection_guide import CONFIG, PROFILE, SLOT, TASK
from taskloop.machine_config import ConfigRefused, Refusal
from taskloop.operations import Adoption
from taskloop.profile import Reason, Refused
from taskloop.slots import NotAdopted, Unadoptable
from taskloop.step_render import human
from taskloop.task import TaskInspectionError


@pytest.mark.parametrize("reason", get_args(Reason.__value__))
def test_each_profile_reason_has_human_guidance_and_preserves_json(
    reason: Reason, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    found = Refused(reason, "key", "arbitrary detail", "target")
    monkeypatch.setattr(cli, "resolve", lambda *_args: found)
    assert cli.main(["profile", "show"]) == 1
    output = capsys.readouterr()
    assert output.out == "" and PROFILE[reason] in output.err and "arbitrary detail" in output.err
    assert cli.main(["profile", "show", "--json"]) == 1
    assert json.loads(capsys.readouterr().err) == {
        "error": {"kind": reason, "side": "target", "key": "key", "message": "arbitrary detail"}}


@pytest.mark.parametrize("reason", get_args(Refusal.__value__))
@pytest.mark.parametrize("command", [["config", "show"], ["drain"]])
def test_each_machine_config_reason_is_guided_in_its_context(
    reason: Refusal, command: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_composition, "load_config", lambda *_args: ConfigRefused(reason, "key", "detail"))
    # Drain imports the owning loader directly.
    monkeypatch.setattr("taskloop.cli_drain.load_config", cli_composition.load_config)
    assert cli.main(command) == 1
    output = capsys.readouterr()
    assert output.out == "" and CONFIG[reason] in output.err and "detail" in output.err


SLOT_REASONS = {
    node.value for alias in ast.walk(ast.parse((ROOT / "slots.py").read_text()))
    if isinstance(alias, ast.TypeAlias) and isinstance(alias.name, ast.Name) and alias.name.id in {"Unclean", "Unadoptable"}
    for node in ast.walk(alias.value) if isinstance(node, ast.Constant) and isinstance(node.value, str)
}


@pytest.mark.parametrize("reason", sorted(SLOT_REASONS))
def test_each_adoption_reason_has_its_own_remedy(reason: Unadoptable) -> None:
    lines = human("tl slot adopt", Adoption((NotAdopted("s1", reason, Path("/slot")),)), None)
    assert SLOT[reason] in lines and len(lines) >= 2


@pytest.mark.parametrize("reason", get_args(TaskInspectionError.__init__.__annotations__["kind"]))
def test_each_task_inspection_failure_keeps_adapter_explanation_and_adds_guidance(
    reason: Literal["not_found", "malformed", "tracker_unavailable", "invalid_binding"],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def inspect(*_args: object) -> None:
        raise TaskInspectionError(reason, "adapter explanation")

    monkeypatch.setattr(cli, "inspect_tracker_task", inspect)
    assert cli.main(["task", "show", "tl-1", "--backlog", "tasks", "--tracker-root", "/tracker"]) == 1
    output = capsys.readouterr()
    assert output.out == "" and TASK[reason] in output.err and "adapter explanation" in output.err


@pytest.mark.parametrize("conclusion", [Conclusion.REFUSED, Conclusion.UNAVAILABLE, Conclusion.INTERRUPTED])
def test_drain_retains_diagnostic_and_explains_what_to_do(conclusion: Conclusion) -> None:
    result = Result(conclusion=conclusion, detail="owning upgrade or observation explanation")
    text = drain_human(result)
    assert result.detail in text and DRAIN_GUIDE[conclusion] in text
