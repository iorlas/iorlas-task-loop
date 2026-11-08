"""delegate-e8z: a codex worker's uv never touches ~/.cache/uv (outside the sandbox) and stays offline while the sandbox has no network."""

from pathlib import Path

import hermetic  # noqa: F401  (a home of its own for every test)

from delegate.app import decide


class CodexUvEnv:
    def test_a_writing_step_caches_inside_its_working_folder_and_uv_is_offline(self):
        e = decide.codex_env({"PATH": "/bin"}, "/w/repo", "workspace-write")
        assert (e["UV_CACHE_DIR"], e["UV_OFFLINE"], e["PATH"]) == ("/w/repo/.task/uv-cache", "1", "/bin")
        assert Path(e["UV_CACHE_DIR"]).is_relative_to("/w/repo")  # codex's workspace-write roots: the working folder
        assert "sandbox_workspace_write.writable_roots=[]" in decide.CODEX_ACCESS

    def test_a_reading_step_uses_no_cache_at_all(self):
        e = decide.codex_env({}, "/w/repo", "read-only")
        assert (e.get("UV_NO_CACHE"), e.get("UV_OFFLINE"), "UV_CACHE_DIR" in e) == ("1", "1", False)

    def test_offline_only_when_the_access_flags_turn_the_network_off(self):
        e = decide.codex_env({}, "/w", "workspace-write", ["-c", "sandbox_workspace_write.network_access=true"])
        assert "UV_OFFLINE" not in e
