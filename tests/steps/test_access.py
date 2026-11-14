"""Effective Codex policy and probe agree, including explicit empty roots and the implement shell environment."""

import json
from pathlib import Path

import pytest
from any_agent.access import CodexSandbox

from taskloop.access import PROBE, agent_env, folders
from taskloop.agents.launch import codex_access
from taskloop.agents.settings import CodexPolicy

FOUND = folders(Path("/home/u/.local/share/task-loop/slots/0123456789ab/s1"))


def which(cmd: str, mode: int = 1, path: str | None = None) -> str | None:
    return f"/bin/{cmd}" if path and mode else None


@pytest.mark.parametrize("prepared", [False, True])
def test_codex_policy_retains_safety_and_uses_the_same_keys_for_probe_and_launch(prepared: bool) -> None:
    policy = codex_access(CodexPolicy(), FOUND if prepared else None)
    config = policy.config()
    keys = {name: json.loads(value) for name, _, value in (flag.partition("=") for flag in config[1::2])}
    assert policy.flags() == ["--ignore-user-config", "--ignore-rules"]
    assert keys["approval_policy"] == "never" and keys["tool_output_token_limit"] == 3000
    assert keys["sandbox_workspace_write.network_access"] is False
    assert keys["sandbox_workspace_write.exclude_slash_tmp"] is True
    assert keys["sandbox_workspace_write.exclude_tmpdir_env_var"] is True
    assert keys["sandbox_workspace_write.writable_roots"] == ([str(p) for p in FOUND.roots] if prepared else [])
    shell = {name.removeprefix("shell_environment_policy.set."): value for name, value in keys.items()
             if name.startswith("shell_environment_policy.set.")}
    assert shell == (agent_env(FOUND) if prepared else {})
    command = ["/bin/sh", "-c", PROBE, "sh", *(str(p) for p in FOUND.roots)]
    argv = policy.sandbox_argv("/bin/codex", command)
    assert argv == ["/bin/codex", "sandbox", "-c", 'sandbox_mode="workspace-write"', *config, "--", *command]
    assert "rm " not in PROBE and "mktemp -d /tmp/" in PROBE


@pytest.mark.parametrize("sandbox", [CodexSandbox.READ_ONLY, CodexSandbox.DANGER_FULL_ACCESS])
def test_other_codex_modes_do_not_receive_workspace_write_tuning(sandbox: CodexSandbox) -> None:
    access = codex_access(CodexPolicy(sandbox=sandbox), FOUND)
    assert access.sandbox is sandbox
    assert not any("sandbox_workspace_write" in flag for flag in access.config())


def test_the_agent_environment_points_uv_and_tmpdir_at_the_roots() -> None:
    assert agent_env(FOUND) == {"TMPDIR": str(FOUND.tmp), "UV_CACHE_DIR": str(FOUND.cache),
                              "UV_TOOL_DIR": str(FOUND.tools), "UV_OFFLINE": "1"}
