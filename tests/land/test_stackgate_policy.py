"""Stack delivery refuses writer-controlled profiles before starting any command."""
from unittest import mock

import pytest
from support.fakegit import FakeGit
from support.memstores import fake_stores

from tlkernel.gitfacts import TreeEntry
from tlland.cmds import Cmds, Stop
from tlland.stackgate import StackGate
from tltestkit.case import Case


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
