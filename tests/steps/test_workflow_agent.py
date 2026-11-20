"""The agent choice of a step: machine configuration, then the workflow's keys, then the flags."""

from pathlib import Path

import pytest

from taskloop.agents.settings import AgentSetting, ClaudePolicy, Overrides, choose
from taskloop.harness_choice import HarnessKind
from taskloop.workflow import Agent

MACHINE = AgentSetting(model="machine-model", effort="high", compaction_token_limit=9000)


def test_an_empty_workflow_agent_leaves_the_machine_setting() -> None:
    assert choose(MACHINE, Agent(), Overrides()) == MACHINE


def test_the_workflow_keys_replace_only_the_keys_it_names() -> None:
    result = choose(MACHINE, Agent(model="wf-model", compaction_token_limit=5000), Overrides())
    assert (result.model, result.effort, result.compaction_token_limit, result.access) == ("wf-model", "high", 5000, MACHINE.access)


def test_a_flag_wins_over_the_workflow_and_the_workflow_over_the_machine() -> None:
    result = choose(MACHINE, Agent(model="wf-model", effort="low"), Overrides(effort="max"))
    assert (result.model, result.effort) == ("wf-model", "max")


def test_a_harness_the_workflow_names_that_differs_from_the_machine_is_refused() -> None:
    with pytest.raises(ValueError, match="machine configuration"):
        choose(MACHINE, Agent(harness=HarnessKind.CLAUDE), Overrides())


def test_a_compaction_limit_needs_the_codex_harness_even_when_the_workflow_sets_it() -> None:
    machine = AgentSetting(harness=HarnessKind.CLAUDE, model="opus", access=ClaudePolicy(settings_file=Path("/policy.json"), settings="{}"))
    with pytest.raises(ValueError, match="compaction_token_limit"):
        choose(machine, Agent(compaction_token_limit=5000), Overrides())
