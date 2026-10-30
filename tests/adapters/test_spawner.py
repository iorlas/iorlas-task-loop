"""adapters/spawner.py on procsim: Spawner.run answers a fake command in process (no patch of subprocess here), builds the child env through
childenv, and the app and cli layers import no subprocess at all (the ruff TID251 ban, no allowlist)."""
import os
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import support.paths  # noqa: F401

# isort: split
from support import procsim

from taskloop.adapters.spawner import RealSpawner

SRC = Path(__file__).resolve().parents[2] / "src" / "taskloop"


class SpawnerOnProcsim(unittest.TestCase):
    def test_a_fake_command_answers_with_its_exit_and_output(self):
        procsim.fake("say-hi", procsim.exits(3, "hi"))
        r = RealSpawner().run(["say-hi"])
        self.assertEqual((r.exit, r.out, r.timed_out), (3, "hi", False))

    def test_a_fake_that_outlasts_the_timeout_is_exit_124(self):
        procsim.fake("slow", procsim.hangs("partial"))
        r = RealSpawner().run(["slow"], timeout_s=5)
        self.assertEqual((r.exit, r.timed_out), (124, True))

    def test_the_child_env_has_no_virtualenv_and_no_unregistered_engine_name(self):
        seen: dict[str, str] = {}

        def spy(cwd, env):
            seen.update(env)
            return 0, ""
        procsim.fake("spy-env", spy)
        base = {"PATH": "/usr/bin", "VIRTUAL_ENV": "/v", "TL_NOT_A_NAME": "1", "KEEP": "k"}
        with mock.patch.dict(os.environ, base, clear=True):
            RealSpawner().run(["spy-env"], extra={"X": "1"})
        self.assertEqual((seen.get("KEEP"), seen.get("X")), ("k", "1"))
        self.assertNotIn("VIRTUAL_ENV", seen)
        self.assertNotIn("TL_NOT_A_NAME", seen)


class LayersStartNoProcess(unittest.TestCase):
    def test_app_and_cli_ban_subprocess_with_no_allowlist(self):
        for layer in ("app", "cli"):
            cfg = tomllib.loads((SRC / layer / "ruff.toml").read_text(encoding="utf-8"))
            self.assertIn("subprocess", cfg["lint"]["flake8-tidy-imports"]["banned-api"], layer)
            for f in sorted((SRC / layer).rglob("*.py")):
                text = f.read_text(encoding="utf-8")
                self.assertNotIn("import subprocess", text, f"{f}: start a process through the Spawner")
                self.assertNotIn("noqa: TID251", text, f"{f}: the ban has no allowlist")


if __name__ == "__main__":
    unittest.main()
