"""The remote delete port is idempotent only when git authoritatively says the ref is absent."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.fakegit import ScriptedGit

# isort: split
from taskloop.contracts.gitfacts import Ref
from taskloop.contracts.slots import SlotGitError


class RemoteDelete(unittest.TestCase):
    def test_success_uses_the_explicit_lease_without_a_probe(self):
        git = ScriptedGit()
        with mock.patch.object(git, "_must") as push, mock.patch.object(git, "ls_remote") as probe:
            git.delete_remote_at("/repo", "origin", "refs/heads/task/a", "checked")
        self.assertEqual(push.call_args.args[1:],
                         ("push", "-q", "--force-with-lease=refs/heads/task/a:checked", "origin", ":refs/heads/task/a"))
        probe.assert_not_called()

    def test_already_absent_is_success_after_a_refused_delete(self):
        git = ScriptedGit()
        with (mock.patch.object(git, "_must", side_effect=SlotGitError("stale info")),
              mock.patch.object(git, "ls_remote", return_value=[]) as probe):
            git.delete_remote_at("/repo", "origin", "refs/heads/task/a", "checked")
        probe.assert_called_once_with("/repo", "origin", "refs/heads/task/a")

    def test_a_moved_ref_and_a_failed_probe_are_failures(self):
        for answer in ([Ref(name="refs/heads/task/a", oid="new")], SlotGitError("offline")):
            with self.subTest(answer=answer):
                git = ScriptedGit()
                with (mock.patch.object(git, "_must", side_effect=SlotGitError("stale info")),
                      mock.patch.object(git, "ls_remote") as probe, self.assertRaises(SlotGitError)):
                    if isinstance(answer, SlotGitError):
                        probe.side_effect = answer
                    else:
                        probe.return_value = answer
                    git.delete_remote_at("/repo", "origin", "refs/heads/task/a", "checked")
