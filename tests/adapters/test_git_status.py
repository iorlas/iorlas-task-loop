"""Status is a read: a run preview must not refresh the worktree's index."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env
from taskloop.contracts.gitfacts import StatusRow


class ReadOnlyStatus(unittest.TestCase):
    def test_status_disables_index_refresh_and_keeps_all_untracked_paths(self):
        git = RealGit(Env())
        result = subprocess.CompletedProcess([], 0, " M src/main.py\0?? new file.txt\0", "")
        with mock.patch.object(git, "_run", return_value=result) as run:
            self.assertEqual(git.status("/worktree", all_untracked=True),
                             [StatusRow(path="src/main.py", index=" ", work="M"),
                              StatusRow(path="new file.txt", index="?", work="?")])
        run.assert_called_once_with("/worktree", "status", "--porcelain", "-z", "--untracked-files=all",
                                    extra={"GIT_OPTIONAL_LOCKS": "0"})
