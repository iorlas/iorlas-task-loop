"""adapters/spawner.py on procsim: Spawner.run answers a fake command in process (no patch of subprocess here), builds the child env through
childenv, and the app and cli layers import no subprocess at all (the ruff TID251 ban, no allowlist)."""
import os
import subprocess
import tomllib
from pathlib import Path
from unittest import mock

# isort: split
from taskloop.adapters.spawner import RealSpawner
from tlkernel.env import snapshot
from tltestkit import procsim
from tltestkit.case import Case

SRC = Path(__file__).resolve().parents[2] / "src" / "taskloop"


class SpawnerOnProcsim(Case):
    def test_timeout_preserves_stdout_and_stderr_for_prepare_diagnostics(self):
        def slow(cwd, env):
            raise subprocess.TimeoutExpired(["slow-restore"], 5, output=b"restoring", stderr=b"feed unavailable")
        procsim.fake("slow-restore", slow)
        r = RealSpawner(snapshot()).run(["slow-restore"], timeout_s=5)
        assert (r.exit, r.out, r.err, r.timed_out) == (124, "restoring", "feed unavailable", True)

    def test_the_child_env_has_no_virtualenv_and_no_unregistered_engine_name(self):
        seen: dict[str, str] = {}

        def spy(cwd, env):
            seen.update(env)
            return 0, ""
        procsim.fake("spy-env", spy)
        base = {"PATH": "/usr/bin", "VIRTUAL_ENV": "/v", "TL_NOT_A_NAME": "1", "KEEP": "k", "LC_ALL": "C"}
        with mock.patch.dict(os.environ, base, clear=True):
            RealSpawner(snapshot()).run(["spy-env"], extra={"X": "1"})
        assert (seen.get("LC_ALL"), seen.get("X")) == ("C", "1")
        assert "KEEP" not in seen  # not on the allowlist
        assert "VIRTUAL_ENV" not in seen
        assert "TL_NOT_A_NAME" not in seen


class LayersStartNoProcess(Case):
    def test_app_and_cli_ban_subprocess_with_no_allowlist(self):
        for layer in ("app", "cli"):
            cfg = tomllib.loads((SRC / layer / "ruff.toml").read_text(encoding="utf-8"))
            assert "subprocess" in cfg["lint"]["flake8-tidy-imports"]["banned-api"], layer
            for f in sorted((SRC / layer).rglob("*.py")):
                text = f.read_text(encoding="utf-8")
                assert "import subprocess" not in text, f"{f}: start a process through the Spawner"
                assert "noqa: TID251" not in text, f"{f}: the ban has no allowlist"
