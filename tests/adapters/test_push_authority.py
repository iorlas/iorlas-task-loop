"""Ordinary Git transport cannot claim that the delivery gate passed."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.git import RealGit
from taskloop.contracts.env import Env


class PushAuthority(unittest.TestCase):
    def test_push_lease_and_delete_do_not_inject_checked_delivery_authority(self):
        git = RealGit(Env(), pinned=False)
        calls = ((git.push, ("repo", "origin", "HEAD:main")),
                 (git.push_lease, ("repo", "origin", "HEAD:topic")),
                 (git.delete_remote_at, ("repo", "origin", "refs/heads/topic", "oid")))
        for method, args in calls:
            with (self.subTest(method=method.__name__),
                  mock.patch.object(git, "_run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run):
                method(*args)
                self.assertNotIn("TL_LAND", run.call_args.kwargs.get("extra") or {})
