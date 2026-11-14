"""The agent's access values (S5e-2): plan's bytes unchanged, the implement agent's three writable roots and environment,
and the sandbox probe's command."""

import tomllib
from pathlib import Path

from any_agent.access import CodexApproval, CodexSandbox

from taskloop.access import CODEX_ACCESS, PROBE, SANDBOX, Sandbox, agent_env, folders, full_access, prepared_access, probe_argv

FOUND = folders(Path("/home/u/.local/share/task-loop/slots/0123456789ab/s1"))
ROOTS = ["/home/u/.local/share/task-loop/slots/0123456789ab/.t/s1", "/home/u/.local/share/task-loop/slots/0123456789ab/.env/s1/uv-cache",
         "/home/u/.local/share/task-loop/slots/0123456789ab/.env/s1/uv-tools"]


def which(cmd: str, mode: int = 1, path: str | None = None) -> str | None:
    return f"/bin/{cmd}" if path and mode else None


def test_plans_access_is_unchanged_byte_for_byte() -> None:
    assert SANDBOX == "workspace-write"
    assert CODEX_ACCESS == (
        "--ignore-user-config", "--ignore-rules", "-c", "sandbox_workspace_write.network_access=false",
        "-c", "sandbox_workspace_write.writable_roots=[]", "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
        "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true", "-c", "approval_policy=never", "-c", "tool_output_token_limit=3000",
    )


def test_the_implement_access_adds_exactly_the_three_roots_and_the_shells_variables() -> None:
    """Network stays off and both `exclude_*` keys stay: /tmp stays closed, TMPDIR (a root) writable. The variables go to
    the agent's shell only (`shell_environment_policy.set`), each value a TOML string."""
    access = prepared_access(FOUND)
    shell = access[len(CODEX_ACCESS):]
    assert shell[0::2] == ("-c",) * 4
    assert {key: tomllib.loads(f"v = {value}")["v"] for key, _, value in (item.partition("=") for item in shell[1::2])} == {
        "shell_environment_policy.set.TMPDIR": ROOTS[0], "shell_environment_policy.set.UV_CACHE_DIR": ROOTS[1],
        "shell_environment_policy.set.UV_TOOL_DIR": ROOTS[2], "shell_environment_policy.set.UV_OFFLINE": "1"}
    changed = [(old, new) for old, new in zip(CODEX_ACCESS, access[:len(CODEX_ACCESS)], strict=True) if old != new]
    assert len(changed) == 1 and changed[0][0] == "sandbox_workspace_write.writable_roots=[]"
    key, _, value = changed[0][1].partition("=")
    assert key == "sandbox_workspace_write.writable_roots" and tomllib.loads(f"roots = {value}")["roots"] == ROOTS
    assert [str(path) for path in (FOUND.tmp, FOUND.cache, FOUND.tools)] == ROOTS


def test_the_agent_environment_points_uv_and_tmpdir_at_the_roots() -> None:
    """No name holds KEY, SECRET or TOKEN (Codex's default policy drops those); they reach only the agent's shell
    (`shell_environment_policy.set`), never the allow-listed environment of Codex's own process."""
    added = agent_env(FOUND)
    assert added == {"TMPDIR": ROOTS[0], "UV_CACHE_DIR": ROOTS[1], "UV_TOOL_DIR": ROOTS[2], "UV_OFFLINE": "1"}
    assert not any(marker in name for name in added for marker in ("KEY", "SECRET", "TOKEN"))


def test_the_probe_runs_codex_sandbox_with_the_agents_keys_on_the_three_roots() -> None:
    """`codex sandbox` takes no `--ignore-*` flag and no `-s`: the mode is a key; every `-c` key of the agent follows."""
    argv = probe_argv("/bin/codex", FOUND)
    split = argv.index("--")
    keys = [item for item in prepared_access(FOUND) if not item.startswith("--")]
    assert argv[:split] == ["/bin/codex", "sandbox", "-c", 'sandbox_mode="workspace-write"', *keys]
    assert argv[split:] == ["--", "/bin/sh", "-c", PROBE, "sh", *ROOTS]
    assert "rm " not in PROBE and "mktemp -d /tmp/" in PROBE  # only its own folders go; /tmp is tried by an unguessable name


def test_full_access_names_no_sandbox_keys_and_never_asks() -> None:
    """Every `-c` it renders is outside the workspace-write keys: nothing there can ask Codex for bwrap."""
    access = full_access(FOUND)
    assert (access.sandbox, access.approval) == (CodexSandbox.DANGER_FULL_ACCESS, CodexApproval.NEVER)
    assert access.flags() == ["--ignore-user-config", "--ignore-rules"]
    assert not any("sandbox_workspace_write" in item for item in access.config())
    assert 'approval_policy="never"' in access.config() and access.config()[-1].startswith("shell_environment_policy.set.")
    assert full_access(None).shell_env == ()
    assert dict(full_access(FOUND).shell_env) == agent_env(FOUND)


def test_the_sandbox_vocabulary_is_the_two_modes_with_workspace_write_the_default() -> None:
    assert [mode.value for mode in Sandbox] == ["workspace-write", "danger-full-access"] and SANDBOX == Sandbox.WORKSPACE_WRITE
