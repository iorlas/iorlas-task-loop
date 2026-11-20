"""The agent boundary: released harnesses, their typed policies and useful launch failures."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import override

from any_agent import ClaudeHarness, CodexHarness, Harness, LaunchInputs, LaunchSpec, OpenCodeHarness
from any_agent.access import ClaudeAccess, CodexAccess, CodexApproval, CodexSandbox
from any_agent.harnesses.opencode_sandbox import Sandbox

from taskloop.access import PROBE, Folders, agent_env, folders
from taskloop.agents.settings import AgentSetting, ClaudePolicy, CodexPolicy, OpenCodePolicy
from taskloop.harness_choice import HarnessKind
from taskloop.ids import Ids

type Credentials = Callable[[HarnessKind], tuple[str, dict[str, str]]]


class CredentialReason(StrEnum):
    PATH = "path"
    EXECUTABLE = "executable"
    HOME = "home"
    AUTH = "auth"


class CredentialsUnavailable(Exception):
    def __init__(self, reason: CredentialReason, explanation: str) -> None:
        super().__init__(explanation)
        if not explanation.strip():
            raise ValueError("credential failure needs an explanation")
        self.reason = reason


@dataclass(frozen=True)
class LaunchFailure:
    reason: str
    explanation: str


@dataclass(frozen=True)
class LaunchedAgent:
    harness: Harness
    spec: LaunchSpec
    credentials: tuple[str, dict[str, str]]
    probe: tuple[str, ...] | None


@dataclass(frozen=True, kw_only=True)
class FactoryCodexAccess(CodexAccess):
    """Limit automatic factory context and override inherited sandbox roots, including empty roots."""

    compaction_token_limit: int | None = None

    @override
    def config(self) -> list[str]:
        config = super().config()
        # https://learn.chatgpt.com/docs/config-file/config-reference (skills.include_instructions)
        # `codex features list` documents the feature names; `codex --help` documents per-run -c overrides.
        config += ["-c", "skills.include_instructions=false",
                   "-c", "features.multi_agent=false",
                   "-c", "features.recommended_plugins=false"]
        if self.sandbox is CodexSandbox.WORKSPACE_WRITE and not self.writable_roots:
            config += ["-c", "sandbox_workspace_write.writable_roots=[]"]
        if self.compaction_token_limit is not None:
            config += ["-c", f"model_auto_compact_token_limit={self.compaction_token_limit}"]
        return config


def codex_access(policy: CodexPolicy, found: Folders | None = None, *, compaction_token_limit: int | None = None) -> CodexAccess:
    shell_env = () if found is None else tuple(agent_env(found).items())
    if policy.sandbox is not CodexSandbox.WORKSPACE_WRITE:
        return FactoryCodexAccess(sandbox=policy.sandbox, approval=CodexApproval.NEVER, tool_output_token_limit=3000,
                                  shell_env=shell_env, ignore_user_config=True, ignore_rules=True,
                                  compaction_token_limit=compaction_token_limit)
    return FactoryCodexAccess(
        sandbox=policy.sandbox, network=False, writable_roots=() if found is None else tuple(str(p) for p in found.roots),
        exclude_slash_tmp=True, exclude_tmpdir=True,
        shell_env=shell_env, approval=CodexApproval.NEVER,
        tool_output_token_limit=3000, ignore_user_config=True, ignore_rules=True,
        compaction_token_limit=compaction_token_limit,
    )


def probe_for(setting: AgentSetting, slot: Path, exe: str) -> tuple[str, ...] | None:
    policy = setting.access
    if not isinstance(policy, CodexPolicy) or policy.sandbox is not CodexSandbox.WORKSPACE_WRITE:
        return None
    found = folders(slot)
    access = codex_access(policy, found, compaction_token_limit=setting.compaction_token_limit)
    command = ["/bin/sh", "-c", PROBE, "sh", *(str(p) for p in found.roots)]
    return tuple(access.sandbox_argv(exe, command))


class AgentLaunch:
    def __init__(self, credentials: Credentials, *, ids: Ids) -> None:
        self.ids = ids
        self.credentials = credentials

    def build(self, setting: AgentSetting, slot: Path, prepared: bool, root: Path, schema: str, out_file: str,
              prompt: str, *, resume: str | None = None) -> LaunchedAgent | LaunchFailure:
        if resume is not None and (not resume or resume.startswith("-") or any(char.isspace() for char in resume)):
            return LaunchFailure("launch:ValueError", "The saved session reference must be nonempty, contain no whitespace "
                                 "and not start with a dash.")
        try:
            exe, env = self.credentials(setting.harness)
        except CredentialsUnavailable as error:
            return LaunchFailure("credentials:" + error.reason, str(error))
        except Exception as error:
            return LaunchFailure("credentials:" + type(error).__name__, "The selected agent's credentials are unavailable.")
        policy = setting.access
        harness: Harness
        probe = None
        access: CodexAccess | ClaudeAccess | None = None
        found = folders(slot) if prepared else None
        if isinstance(policy, CodexPolicy):
            harness = CodexHarness(resume=resume)
            access = codex_access(policy, found, compaction_token_limit=setting.compaction_token_limit)
            if found is not None:
                probe = probe_for(setting, slot, exe)
        elif isinstance(policy, ClaudePolicy):
            harness = ClaudeHarness()
            access = ClaudeAccess(permission_mode=policy.permission_mode, settings=policy.settings)
        elif isinstance(policy, OpenCodePolicy):
            box = policy.sandbox
            harness = OpenCodeHarness(root=root, sandbox=Sandbox(readable=box.readable, scratch=box.scratch, runners=box.runners))
        try:
            contract = Path(schema).read_text(encoding="utf-8")
            prompt += "\nReturn exactly one JSON object satisfying this answer schema:\n" + contract
            inputs = LaunchInputs(exe=exe, cwd=str(slot), model=setting.model, effort=setting.effort, prompt=prompt,
                                  env=env, schema=schema, out_file=out_file, access_policy=access, write=True,
                                  session=self.ids.session() if resume is None else resume, resume=resume)
            return LaunchedAgent(harness, harness.launch_spec(inputs), (exe, env), probe)
        except Exception as error:
            harness.cleanup()
            return LaunchFailure("launch:" + type(error).__name__, f"The selected agent's launch could not be prepared "
                                 f"({type(error).__name__}).")
