"""The agent's access values (S5e-2): plan's bytes unchanged, the implement agent's three writable roots and environment,
and the sandbox probe's command."""

import tomllib
from pathlib import Path

from taskloop.access import CODEX_ACCESS, PROBE, SANDBOX, agent_env, folders, prepared_access, probe_argv
from taskloop.composition import codex_machine_credentials

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


def test_the_implement_access_adds_exactly_the_three_roots_as_a_toml_array() -> None:
    """Network stays off and both `exclude_*` keys stay: /tmp stays closed, TMPDIR (a root) writable."""
    access = prepared_access(FOUND)
    changed = [(old, new) for old, new in zip(CODEX_ACCESS, access, strict=True) if old != new]
    assert len(changed) == 1 and changed[0][0] == "sandbox_workspace_write.writable_roots=[]"
    key, _, value = changed[0][1].partition("=")
    assert key == "sandbox_workspace_write.writable_roots" and tomllib.loads(f"roots = {value}")["roots"] == ROOTS
    assert [str(path) for path in (FOUND.tmp, FOUND.cache, FOUND.tools)] == ROOTS


def test_the_agent_environment_points_uv_and_tmpdir_at_the_roots_and_survives_the_scrub() -> None:
    """No name holds KEY, SECRET or TOKEN (Codex's default policy drops those), and the factory's own scrub keeps them."""
    added = agent_env(FOUND)
    assert added == {"TMPDIR": ROOTS[0], "UV_CACHE_DIR": ROOTS[1], "UV_TOOL_DIR": ROOTS[2], "UV_OFFLINE": "1"}
    assert not any(marker in name for name in added for marker in ("KEY", "SECRET", "TOKEN"))
    environ = {"PATH": "/bin", "HOME": "/home/u", **added}
    _exe, env = codex_machine_credentials(environ, which=which, exists=lambda _path: True)
    assert {name: env[name] for name in added} == added


def test_the_probe_runs_codex_sandbox_with_the_agents_keys_on_the_three_roots() -> None:
    """`codex sandbox` takes no `--ignore-*` flag and no `-s`: the mode is a key; every `-c` key of the agent follows."""
    argv = probe_argv("/bin/codex", FOUND)
    split = argv.index("--")
    keys = [item for item in prepared_access(FOUND) if not item.startswith("--")]
    assert argv[:split] == ["/bin/codex", "sandbox", "-c", 'sandbox_mode="workspace-write"', *keys]
    assert argv[split:] == ["--", "/bin/sh", "-c", PROBE, "sh", *ROOTS]
    assert "rm " not in PROBE and "exit 4" in PROBE  # it removes only its own folders, and fails when /tmp is writable
