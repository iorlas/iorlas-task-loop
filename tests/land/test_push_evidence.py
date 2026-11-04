"""Commands without runs keep push evidence under the explicitly supplied config directory."""
import tempfile
import unittest
from pathlib import Path

import support.paths  # noqa: F401
from support.fakegit import ScriptedGit
from support.forgesim import ForgeSim

# isort: split
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.forge import Forge
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.slots import SlotGitError
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class RefusingGit(ScriptedGit):
    def push(self, d: str, remote: str, refspec: str) -> None:
        raise SlotGitError("gate: refusing the push: run just check")


class Evidence(unittest.TestCase):
    def test_no_run_uses_timestamp_and_branch_under_config_land_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ConfigDir(tmp)
            log = RunLog(fake_stores().run_log("r"))
            cmds = Cmds(ForgeSim(), log, tmp, config=config)
            forge = Forge(cmds, RefusingGit(), tmp, "main")
            for _ in range(2):
                with self.assertRaises(Stop) as raised:
                    forge.push("task/topic", "a" * 40)
                self.assertIn("gate: refusing the push: run just check", raised.exception.why)
            files = sorted((Path(tmp) / "land-push").glob("*-task_topic.log"))
            self.assertEqual(len(files), 2)
            self.assertTrue(all(path.name.partition("-")[0].isdigit() for path in files))
            self.assertTrue(all(path.read_text() == "gate: refusing the push: run just check" for path in files))
            self.assertTrue(any(str(path) in raised.exception.why for path in files))
