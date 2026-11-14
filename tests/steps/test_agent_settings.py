"""Agent settings depend only on their feature and the shared harness/provider vocabulary."""

from pathlib import Path

import pytest
from any_agent.access import ClaudePermissionMode
from pydantic import ValidationError

from taskloop.agents.config import resolve_agents
from taskloop.agents.settings import (
    AgentSetting,
    ClaudePolicy,
    CodexPolicy,
    OpenCodePolicy,
    Overrides,
    StepSettings,
    apply,
    decode_setting,
    encode_policy,
)
from taskloop.harness_choice import HarnessKind, Provider


def test_defaults_and_individual_overrides_are_selected_for_the_actual_step() -> None:
    settings = StepSettings()
    assert settings.plan.model == settings.implement.model == "gpt-6.1-sol"
    assert settings.plan.effort == "high" and settings.implement.effort == "medium"
    assert apply(settings.plan, Overrides(model="custom")).effort == "high"
    assert apply(settings.implement, Overrides(effort="ultra")).model == "gpt-6.1-sol"
    with pytest.raises(ValueError, match="matching per-step"):
        apply(settings.plan, Overrides(harness=HarnessKind.CLAUDE, model="opus"))


@pytest.mark.parametrize("limit", [None, 1, 100000])
def test_compaction_resolves_and_survives_flags_and_storage(limit: int | None, tmp_path: Path) -> None:
    settings, sources = resolve_agents({"implement": {"compaction_token_limit": limit}}, tmp_path)
    setting = settings.implement
    assert setting.compaction_token_limit == limit
    assert settings.plan.compaction_token_limit is None
    assert sources["agents.implement.compaction_token_limit"] == "file"
    overridden = apply(setting, Overrides(model="custom", effort="low"))
    assert overridden.compaction_token_limit == limit
    assert decode_setting(overridden.harness, overridden.provider, overridden.model, overridden.effort,
                          encode_policy(overridden.access), limit) == overridden


@pytest.mark.parametrize("limit", [True, False, "100000", 100000.0, 1.5, 0, -1])
def test_compaction_rejects_coercion_and_nonpositive_counts(limit: object, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="compaction_token_limit"):
        resolve_agents({"plan": {"compaction_token_limit": limit}}, tmp_path)
    with pytest.raises(ValidationError, match="compaction_token_limit"):
        AgentSetting.model_validate({"compaction_token_limit": limit})


@pytest.mark.parametrize("harness", [HarnessKind.CLAUDE, HarnessKind.OPENCODE])
def test_compaction_requires_codex_before_policy_io(harness: HarnessKind, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="compaction_token_limit requires codex"):
        resolve_agents({"plan": {"harness": harness, "model": "chosen", "compaction_token_limit": 100000}}, tmp_path)
    policy = ClaudePolicy(settings_file=tmp_path / "absent.json", settings="{}") if harness is HarnessKind.CLAUDE else OpenCodePolicy()
    with pytest.raises(ValidationError, match="compaction_token_limit requires codex"):
        AgentSetting(harness=harness, model="chosen", access=policy, compaction_token_limit=100000)


@pytest.mark.parametrize("limit", [0, -1])
def test_stored_compaction_passes_the_setting_validator(limit: int) -> None:
    with pytest.raises(ValidationError, match="compaction_token_limit"):
        decode_setting("codex", "openai", "chosen", "high", encode_policy(CodexPolicy()), limit)


@pytest.mark.parametrize("text", ["", " ", "-model", "two words", "bad\nword", "bad\x00word"])
def test_bad_identifiers_are_refused_at_the_typed_edge(text: str) -> None:
    with pytest.raises(ValidationError):
        Overrides(model=text)
    with pytest.raises(ValidationError):
        AgentSetting(effort=text)


def test_file_choices_capture_policy_and_never_reload_for_a_repeat(tmp_path: Path) -> None:
    path = tmp_path / "claude.json"
    path.write_text('{"hooks":{"opaque":"private"}}')
    settings, sources = resolve_agents({"plan": {"harness": "claude", "model": "opus", "access": {
        "settings_file": "~/claude.json", "permission_mode": "acceptEdits"}}, "implement": {"effort": "low"}}, tmp_path)
    plan = settings.plan
    assert sources["agents.plan.model"] == "file" and sources["agents.implement.effort"] == "file"
    assert plan.provider is Provider.ANTHROPIC and plan.effort == "high"
    assert isinstance(plan.access, ClaudePolicy) and plan.access.permission_mode is ClaudePermissionMode.ACCEPT_EDITS
    encoded = encode_policy(plan.access)
    path.unlink()
    reopened = decode_setting(plan.harness, plan.provider, plan.model, plan.effort, encoded)
    assert reopened == plan and isinstance(reopened.access, ClaudePolicy)
    assert "private" in reopened.access.settings
    assert "private" not in plan.summary
    assert settings.implement.effort == "low" and isinstance(settings.implement.access, CodexPolicy)


def test_opencode_typed_sandbox_is_captured_without_a_platform_probe(tmp_path: Path) -> None:
    path = tmp_path / "sandbox.json"
    path.write_text('{"readable":["/opt/tools"],"scratch":".local/tmp","runners":["uv"]}')
    settings, _sources = resolve_agents({"implement": {"harness": "opencode", "model": "unknown/model",
                                       "access": {"sandbox_file": str(path)}}}, tmp_path)
    setting = settings.implement
    assert setting.provider is Provider.UNKNOWN and isinstance(setting.access, OpenCodePolicy)
    assert setting.access.sandbox.readable == ("/opt/tools",) and setting.access.sandbox.runners == ("uv",)
    path.write_text("[]")
    assert decode_setting(setting.harness, setting.provider, setting.model, setting.effort, encode_policy(setting.access)) == setting


@pytest.mark.parametrize("value", [
    {"check": {}}, {"plan": {"provider": "openai"}}, {"plan": {"model": ""}}, {"plan": {"effort": ""}},
    {"plan": {"harness": "claude"}}, {"plan": {"harness": "opencode"}},
    {"plan": {"access": {"sandbox": "bad"}}}, {"plan": {"access": {"permission_mode": "auto"}}},
    {"plan": {"harness": "claude", "model": "opus", "access": {"settings_file": "relative.json"}}},
    {"plan": {"harness": "claude", "model": "opus", "access": {"settings_file": "/missing/settings.json"}}},
    {"plan": {"harness": "claude", "model": "opus", "access": {"settings_file": "/a", "permission_mode": "unsafe"}}},
])
def test_invalid_configuration_never_becomes_a_step_setting(value: object, tmp_path: Path) -> None:
    with pytest.raises((ValueError, OSError)):
        resolve_agents(value, tmp_path)


@pytest.mark.parametrize("harness,contents", [("claude", "[]"), ("claude", "bad"), ("opencode", "[]"),
                                            ("opencode", '{"runners":["-bad"]}'), ("opencode", '{"scratch":"../other"}'),
                                            ("opencode", '{"unknown":true}')])
def test_policy_documents_are_validated_before_admission(tmp_path: Path, harness: str, contents: str) -> None:
    path = tmp_path / "policy.json"
    path.write_text(contents)
    field = "settings_file" if harness == "claude" else "sandbox_file"
    with pytest.raises(ValueError, match=r"agents\.plan"):
        resolve_agents({"plan": {"harness": harness, "model": "chosen", "access": {field: str(path)}}}, tmp_path)
