"""Stack delivery refuses writer-controlled profiles before starting any command."""
import sys
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import FakeGit

from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.stackgate import StackGate
from taskloop.contracts.gitfacts import TreeEntry
from taskloop.stores.memory import fake_stores


class StackPolicy(Case):
    def test_changed_added_or_removed_profile_stops_before_any_command(self):
        base = [TreeEntry(mode="100644", kind="blob", oid="base-profile", path=".task-loop.json")]
        tip = [TreeEntry(mode="100644", kind="blob", oid="tip-profile", path=".task-loop.json")]
        for before, after in ((base, tip), (base, []), ([], tip)):
            with self.subTest(before=before, after=after):
                git = FakeGit(**{"rev_parse__origin/main": "base"})
                cmds = mock.Mock(spec=Cmds)
                cmds.port.side_effect = lambda text, fn: fn()
                gate = StackGate(cmds, git, fake_stores(), "/repo", "origin/main", ["tl"])
                with (mock.patch.object(git, "ls_tree", side_effect=[before, after]),
                      mock.patch.object(gate, "red") as red, pytest.raises(Stop) as raised):
                    gate.require("task/a", "tip")
                assert raised.value.rc == 1
                assert raised.value.why == ("profile_changed: task/a changes .task-loop.json; only the owner may push "
                                 "a profile change (git push --no-verify)")
                red.assert_not_called()
                cmds.run.assert_not_called()
