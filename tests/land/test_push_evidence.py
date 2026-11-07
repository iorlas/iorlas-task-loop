"""Commands without runs keep push evidence under the explicitly supplied config directory."""
from pathlib import Path

import support.paths  # noqa: F401
from support.fakegit import ScriptedGit
from support.forgesim import ForgeSim

from tltestkit.tmpdir import TemporaryDirectory

# isort: split
import pytest
from support.memstores import fake_stores

from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.forge import Forge
from taskloop.stores.runlog import RunLog
from tlkernel.paths import ConfigDir
from tlkernel.slots import SlotGitError
from tltestkit.case import Case


class RefusingGit(ScriptedGit):
    def push(self, d: str, remote: str, refspec: str) -> None:
        raise SlotGitError("gate: refusing the push: run just check")


class Evidence(Case):
    def test_no_run_uses_timestamp_and_branch_under_config_land_push(self):
        with TemporaryDirectory() as tmp:
            config = ConfigDir(tmp)
            log = RunLog(fake_stores().run_log("r"))
            cmds = Cmds(ForgeSim(), log, tmp, config=config)
            forge = Forge(cmds, RefusingGit(), tmp, "main")
            for _ in range(2):
                with pytest.raises(Stop) as raised:
                    forge.push("task/topic", "a" * 40)
                assert "gate: refusing the push: run just check" in raised.value.why
            files = sorted((Path(tmp) / "land-push").glob("*-task_topic.log"))
            assert len(files) == 2
            assert all(path.name.partition("-")[0].isdigit() for path in files)
            assert all(path.read_text() == "gate: refusing the push: run just check" for path in files)
            assert any(str(path) in raised.value.why for path in files)
