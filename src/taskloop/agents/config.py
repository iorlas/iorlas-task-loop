"""Machine-file inputs, resolved once with captured policy documents and explicit home."""

from pathlib import Path

from any_agent.access import ClaudePermissionMode, CodexSandbox
from pydantic import Field, JsonValue, ValidationError

from taskloop.agents.settings import (
    AgentSetting,
    ClaudePolicy,
    CodexPolicy,
    Input,
    OpenCodePolicy,
    OpenCodeSandbox,
    StepSettings,
)
from taskloop.harness_choice import HarnessKind


class CodexInput(Input):
    sandbox: CodexSandbox = CodexSandbox.WORKSPACE_WRITE


class ClaudeInput(Input):
    settings_file: str
    permission_mode: ClaudePermissionMode = ClaudePermissionMode.DONT_ASK


class OpenCodeInput(Input):
    sandbox_file: str | None = None


class StepInput(Input):
    harness: HarnessKind = HarnessKind.CODEX
    model: str | None = None
    effort: str | None = None
    access: dict[str, JsonValue] = Field(default_factory=dict)


class AgentsInput(Input):
    plan: StepInput = StepInput()
    implement: StepInput = StepInput()


def path_at(value: str, home: Path) -> Path:
    path = home / value[2:] if value.startswith("~/") else home if value == "~" else Path(value)
    if not path.is_absolute() or not value.isprintable():
        raise ValueError("must be an absolute or home-expanded path")
    return path


def _setting(raw: StepInput, home: Path, built: AgentSetting) -> AgentSetting:
    model = raw.model
    effort = raw.effort if raw.effort is not None else built.effort
    if raw.harness is HarnessKind.CODEX:
        access = CodexInput.model_validate(raw.access)
        policy = CodexPolicy(sandbox=access.sandbox)
        return AgentSetting(model=model if model is not None else built.model, effort=effort, access=policy)
    if model is None:
        raise ValueError("model is required when harness is not codex")
    if raw.harness is HarnessKind.CLAUDE:
        claude = ClaudeInput.model_validate(raw.access)
        path = path_at(claude.settings_file, home)
        policy = ClaudePolicy(settings_file=path, settings=path.read_text(), permission_mode=claude.permission_mode)
    else:
        opencode = OpenCodeInput.model_validate(raw.access)
        path = None if opencode.sandbox_file is None else path_at(opencode.sandbox_file, home)
        sandbox = OpenCodeSandbox() if path is None else OpenCodeSandbox.model_validate_json(path.read_text())
        policy = OpenCodePolicy(sandbox_file=path, sandbox=sandbox)
    return AgentSetting(harness=raw.harness, model=model, effort=effort, access=policy)


def resolve_agents(value: object, home: Path) -> tuple[StepSettings, dict[str, str]]:
    raw = AgentsInput.model_validate(value)
    settings: dict[str, AgentSetting] = {}
    sources: dict[str, str] = {}
    built = StepSettings()
    for step, entry, default in (("plan", raw.plan, built.plan), ("implement", raw.implement, built.implement)):
        try:
            settings[step] = _setting(entry, home, default)
        except (ValueError, OSError) as error:
            raise ValueError(f"agents.{step}: {error}") from error
        for field in ("harness", "model", "effort"):
            if field in entry.model_fields_set:
                sources[f"agents.{step}.{field}"] = "file"
        for field in ("sandbox", "settings_file", "permission_mode", "sandbox_file"):
            if field in entry.access:
                sources[f"agents.{step}.access.{field}"] = "file"
    return StepSettings(plan=settings["plan"], implement=settings["implement"]), sources


def configuration_error(error: ValueError | OSError) -> tuple[str, str]:
    if isinstance(error, ValidationError):
        location = ".".join(str(part) for part in error.errors()[0]["loc"])
        return "agents" + ("." + location if location else ""), str(error)
    key = str(error).split(":", 1)[0]
    return key if key.startswith("agents.") else "agents", str(error)


def display(settings: StepSettings, sources: dict[str, str]) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for step in ("plan", "implement"):
        setting = settings.for_step(step)
        values = {"harness": setting.harness.value, "provider": setting.provider.value,
                  "model": setting.model, "effort": setting.effort, "access.summary": setting.summary}
        access = setting.access
        if isinstance(access, CodexPolicy):
            values["access.sandbox"] = str(access.sandbox)
        elif isinstance(access, ClaudePolicy):
            values.update({"access.settings_file": str(access.settings_file), "access.permission_mode": str(access.permission_mode)})
        elif access.sandbox_file is not None:
            values["access.sandbox_file"] = str(access.sandbox_file)
        for name, value in values.items():
            key = f"agents.{step}.{name}"
            found[key] = {"value": value, "source": "derived" if name in {"provider", "access.summary"} else sources.get(key, "default")}
    return found
