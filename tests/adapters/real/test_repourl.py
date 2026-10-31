"""repo_url names a repo the same from its main checkout and from a slot, with or without an origin remote (tl-6bv: the loop read the
storm record by the main checkout's path, the engine wrote it by its slot's path)."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from support.spawn import port_git

from taskloop.adapters.repourl import repo_url


class RepoUrl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = str(Path(self.tmp.name, "repo").resolve())
        self.slot = str(Path(self.tmp.name, "slot").resolve())
        ident = ["-c", "user.email=t@t", "-c", "user.name=t"]
        for argv in (["init", "-q", "-b", "main", self.repo], ["-C", self.repo, *ident, "commit", "-q", "--allow-empty", "-m", "i"],
                     ["-C", self.repo, "worktree", "add", "-q", "--detach", self.slot]):
            subprocess.run(["git", *argv], check=True, capture_output=True)
        self.git = port_git()

    def test_with_no_remote_a_slot_and_the_main_checkout_have_one_name(self):
        self.assertEqual(repo_url(self.git, self.slot), repo_url(self.git, self.repo))
        self.assertNotEqual(repo_url(self.git, self.repo), self.repo)

    def test_the_origin_url_wins_when_there_is_one(self):
        subprocess.run(["git", "-C", self.repo, "remote", "add", "origin", "git@h:o/r.git"], check=True)
        self.assertEqual(repo_url(self.git, self.slot), "git@h:o/r.git")
        self.assertEqual(repo_url(self.git, self.repo), "git@h:o/r.git")


if __name__ == "__main__":
    unittest.main()
