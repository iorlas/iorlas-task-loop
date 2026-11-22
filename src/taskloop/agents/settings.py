"""Immutable per-step choices, stored policies and their single database codec."""

import json
from pathlib import Path
from typing import Annotated, Literal, Self

from any_agent.access import ClaudePermissionMode, CodexSandbox
from any_agent.harnesses.opencode_sandbox import Sandbox
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, field_validator, model_validator

from taskloop.agents.effort import accepted
from taskloop.harness_choice import HarnessKind, Provider, provider_of
from taskloop.step import Step, decode_step
from taskloop.workflow import Agent


class Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class EffortRefused(ValueError):
    """An effort level the chosen harness and model are known not to accept."""


def require_effort(effort: str, harness: HarnessKind, model: str, home: Path) -> None:
    """Refuse an effort level that is known not to be accepted; a level the harness cannot judge passes."""
    levels = accepted(harness, model, home)
    if levels is not None and effort not in levels:
        raise EffortRefused(f"effort {effort!r} is not accepted by {harness} model {model!r}; it accepts {', '.join(levels)}")


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


class Overrides(Input):
    harness: HarnessKind | None = None
    model: str | None = None
    plan_effort: str | None = None
    implement_effort: str | None = None

    @field_validator("model", "plan_effort", "implement_effort")
    @classmethod
    def word(cls, value: str | None) -> str | None:
        return None if value is None else identifier(value)

    def effort_for(self, step: str) -> str | None:
        return self.plan_effort if decode_step(step) is Step.PLAN else self.implement_effort


class StepSettings(Input):
    plan: AgentSetting = AgentSetting()
    implement: AgentSetting = AgentSetting(effort="medium")

    def for_step(self, step: str) -> AgentSetting:
        return self.plan if decode_step(step) is Step.PLAN else self.implement

    def require_flags(self, flags: Overrides, home: Path) -> Overrides:
        """`flags`, each effort level checked against the step's machine harness and the model the flags leave it."""
        for step in Step:
            effort, setting = flags.effort_for(step), self.for_step(step)
            if effort is not None:
                require_effort(effort, setting.harness, flags.model or setting.model, home)
        return flags

    def overridden(self, flags: Overrides) -> Self:
        return type(self)(plan=apply(self.plan, flags, Step.PLAN), implement=apply(self.implement, flags, Step.IMPLEMENT))


def apply(setting: AgentSetting, flags: Overrides, step: str) -> AgentSetting:
    if flags.harness is not None and flags.harness is not setting.harness:
        raise ValueError(f"{flags.harness} needs matching per-step model and access configuration")
    return AgentSetting(
        harness=setting.harness,
        model=flags.model or setting.model,
        effort=flags.effort_for(step) or setting.effort,
        access=setting.access,
        compaction_token_limit=setting.compaction_token_limit,
    )


def choose(machine: AgentSetting, workflow: Agent, flags: Overrides, step: str) -> AgentSetting:
    """The step's agent choice: `machine`, then each key the workflow names, then the flags (decision 18). Sandbox, access and
    credentials stay the machine's. A harness the workflow names that differs from the machine's is refused like the flag case
    (`ValueError`), since the model and access policy of another harness are machine configuration."""
    if workflow.harness is not None and workflow.harness is not machine.harness:
        raise ValueError(f"The workflow names harness {workflow.harness}, but the machine configuration sets {machine.harness}")
    named = AgentSetting(
        harness=machine.harness,
        model=machine.model if workflow.model is None else workflow.model,
        effort=machine.effort if workflow.effort is None else workflow.effort,
        access=machine.access,
        compaction_token_limit=(
            machine.compaction_token_limit if workflow.compaction_token_limit is None else workflow.compaction_token_limit
        ),
    )
    return apply(named, flags, step)


def encode_policy(policy: Policy) -> str:
    return POLICY.dump_json(policy).decode()


def decode_setting(
    harness: str, provider: str, model: str, effort: str, policy: str, compaction_token_limit: int | None = None
) -> AgentSetting:
    setting = AgentSetting(
        harness=HarnessKind(harness),
        model=model,
        effort=effort,
        access=POLICY.validate_json(policy),
        compaction_token_limit=compaction_token_limit,
    )
    if setting.provider != provider:
        raise ValueError("stored provider does not match harness and model")
    return setting
