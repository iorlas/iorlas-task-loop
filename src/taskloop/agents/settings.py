"""Immutable per-step choices, stored policies and their single database codec."""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from any_agent.access import ClaudePermissionMode, CodexSandbox
from any_agent.harnesses.opencode_sandbox import Sandbox
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, field_validator, model_validator

from taskloop.harness_choice import HarnessKind, Provider, provider_of


class Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


def identifier(value: str) -> str:
    if not value or value.startswith("-") or not value.isprintable() or any(c.isspace() for c in value):
        raise ValueError("must be one printable word that does not start with '-'")
    return value


class CodexPolicy(Input):
    harness: Literal[HarnessKind.CODEX] = HarnessKind.CODEX
    sandbox: CodexSandbox = CodexSandbox.WORKSPACE_WRITE

    @property
    def summary(self) -> str:
        return str(self.sandbox)


class ClaudePolicy(Input):
    harness: Literal[HarnessKind.CLAUDE] = HarnessKind.CLAUDE
    settings_file: Path
    settings: str
    permission_mode: ClaudePermissionMode = ClaudePermissionMode.DONT_ASK

    @field_validator("settings")
    @classmethod
    def document(cls, value: str) -> str:
        parsed = TypeAdapter(dict[str, JsonValue]).validate_json(value)
        return json.dumps(parsed, separators=(",", ":"), sort_keys=True, allow_nan=False)

    @field_validator("settings_file")
    @classmethod
    def absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("must be an absolute path")
        return value

    @property
    def summary(self) -> str:
        return f"permissions {self.permission_mode}; captured settings"


OPENCODE_DEFAULTS = Sandbox()


class OpenCodeSandbox(Input):
    readable: tuple[str, ...] = OPENCODE_DEFAULTS.readable
    scratch: str = OPENCODE_DEFAULTS.scratch
    runners: tuple[str, ...] = OPENCODE_DEFAULTS.runners

    @field_validator("readable")
    @classmethod
    def roots(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not Path(each).is_absolute() or not each.isprintable() for each in value):
            raise ValueError("readable roots must be absolute paths")
        return value

    @field_validator("scratch")
    @classmethod
    def relative(cls, value: str) -> str:
        if not value or not value.isprintable() or Path(value).is_absolute() or ".." in Path(value).parts or value == ".":
            raise ValueError("scratch must name a folder within the worktree")
        return value

    @field_validator("runners")
    @classmethod
    def commands(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(identifier(each) for each in value)


class OpenCodePolicy(Input):
    harness: Literal[HarnessKind.OPENCODE] = HarnessKind.OPENCODE
    sandbox_file: Path | None = None
    sandbox: OpenCodeSandbox = OpenCodeSandbox()

    @field_validator("sandbox_file")
    @classmethod
    def absolute(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("must be an absolute path")
        return value

    @property
    def summary(self) -> str:
        return "captured sandbox" if self.sandbox_file else "default sandbox"


type Policy = Annotated[CodexPolicy | ClaudePolicy | OpenCodePolicy, Field(discriminator="harness")]
POLICY = TypeAdapter(Policy)


class AgentSetting(Input):
    harness: HarnessKind = HarnessKind.CODEX
    model: str = "gpt-6.1-sol"
    effort: str = "high"
    access: Policy = CodexPolicy()
    compaction_token_limit: int | None = Field(default=None, strict=True, gt=0)

    _identifiers = field_validator("model", "effort")(identifier)

    @model_validator(mode="after")
    def matching(self) -> Self:
        if self.compaction_token_limit is not None and self.harness is not HarnessKind.CODEX:
            raise ValueError("compaction_token_limit requires codex")
        if self.harness is not self.access.harness:
            raise ValueError("access policy must match harness")
        if self.harness is not HarnessKind.CODEX and "model" not in self.model_fields_set:
            raise ValueError("model is required for this harness")
        return self

    @property
    def provider(self) -> Provider:
        return provider_of(self.harness, self.model)

    @property
    def summary(self) -> str:
        return self.access.summary


class AgentStep(StrEnum):
    PLAN = "plan"
    IMPLEMENT = "implement"


class Overrides(Input):
    harness: HarnessKind | None = None
    model: str | None = None
    effort: str | None = None

    @field_validator("model", "effort")
    @classmethod
    def word(cls, value: str | None) -> str | None:
        return None if value is None else identifier(value)


class StepSettings(Input):
    plan: AgentSetting = AgentSetting()
    implement: AgentSetting = AgentSetting(effort="medium")

    def for_step(self, step: str) -> AgentSetting:
        return self.plan if AgentStep(step) is AgentStep.PLAN else self.implement

    def overridden(self, flags: Overrides) -> Self:
        return type(self)(plan=apply(self.plan, flags), implement=apply(self.implement, flags))


def apply(setting: AgentSetting, flags: Overrides) -> AgentSetting:
    if flags.harness is not None and flags.harness is not setting.harness:
        raise ValueError(f"{flags.harness} needs matching per-step model and access configuration")
    return AgentSetting(harness=setting.harness, model=flags.model or setting.model, effort=flags.effort or setting.effort,
                        access=setting.access, compaction_token_limit=setting.compaction_token_limit)


def encode_policy(policy: Policy) -> str:
    return POLICY.dump_json(policy).decode()


def decode_setting(harness: str, provider: str, model: str, effort: str, policy: str,
                   compaction_token_limit: int | None = None) -> AgentSetting:
    setting = AgentSetting(harness=HarnessKind(harness), model=model, effort=effort, access=POLICY.validate_json(policy),
                           compaction_token_limit=compaction_token_limit)
    if setting.provider != provider:
        raise ValueError("stored provider does not match harness and model")
    return setting
