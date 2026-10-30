"""One origin, one land lock and one release lock, however the remote URL is spelled (ssh and https used to make two locks)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

# isort: split
from taskloop.adapters import landlock
from taskloop.app.release.push import release_lock_path

SPELLINGS = ["git@github.com:iorlas/task-loop.git", "ssh://git@github.com/iorlas/task-loop", "ssh://git@github.com:22/iorlas/task-loop.git",
             "https://github.com/iorlas/task-loop.git", "https://github.com/iorlas/task-loop/", "HTTPS://me@GitHub.com/iorlas/task-loop.git",
             "github.com:iorlas/task-loop"]


class RemoteLockKey(unittest.TestCase):
    def test_every_spelling_of_one_remote_is_one_name(self):
        self.assertEqual({landlock.canonical_remote(u) for u in SPELLINGS}, {"github.com/iorlas/task-loop"})

    def test_one_land_lock_and_one_release_lock_per_remote(self):
        self.assertEqual(len({landlock.land_lock_path(u) for u in SPELLINGS}), 1)
        self.assertEqual(len({release_lock_path(Path("/c"), u) for u in SPELLINGS}), 1)

    def test_another_repo_or_host_is_another_lock(self):
        a = landlock.land_lock_path("git@github.com:iorlas/task-loop.git")
        self.assertNotEqual(a, landlock.land_lock_path("git@github.com:iorlas/other.git"))
        self.assertNotEqual(a, landlock.land_lock_path("git@gitlab.com:iorlas/task-loop.git"))

    def test_a_local_path_stays_as_it_is(self):
        self.assertEqual(landlock.canonical_remote("/srv/git/repo.git"), "/srv/git/repo.git")
        self.assertEqual(landlock.canonical_remote("../repo"), "../repo")
