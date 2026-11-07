"""The loop's chores step files delegate's status again when the snapshot is 20 minutes old, and not more often, failures included."""
import json
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.spawn import real_spawner

from taskloop.app.wire import lanes
from tlkernel.delegate_status import snapshot_of
from tlkernel.env import Env
from tlkernel.paths import ConfigDir
from tlkernel.rowstores import StatusStore

REAL = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "delegate_status_0.51.0_real.json").read_text())


class Chore(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(Path(self.tmp.name) / "task-loop")
        self.said = []

    def chore(self, now, why=None):
        with mock.patch.object(lanes, "file_status", return_value=why) as ask:
            return lanes.chore(self.said.append, real_spawner(), Env({"XDG_CONFIG_HOME": self.tmp.name}), now), ask.call_count

    def test_nothing_filed_asks_once_then_waits_20_minutes_even_when_it_failed(self):
        assert self.chore(5000.0, "delegate status exited 1: x") == (True, 1)
        assert self.said == ["loop: delegate status exited 1: x"]
        assert self.chore(5000.0 + lanes.EVERY_S - 1) == (False, 0)
        assert self.chore(5000.0 + lanes.EVERY_S) == (True, 1)

    def test_a_fresh_snapshot_is_left_alone_and_an_old_one_is_asked_again(self):
        StatusStore(self.cfg).write(snapshot_of(REAL))
        at = REAL["ts"]
        assert self.chore(at + 60) == (False, 0)
        assert self.chore(at + lanes.EVERY_S + 1) == (True, 1)
